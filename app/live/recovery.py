"""Read-only storage diagnostics and Etsy listing reconciliation.

Nothing here generates art, creates/edits/publishes/deletes Etsy listings or
places Printful orders. The only network call is the explicit, user-triggered
``preview_etsy_listings`` (read-only GETs); importing the preview is a purely
local, confirmed step that adds clearly-labelled ``recovered_unverified``
records which can never be approved, published or fulfilled from this app.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, List, Optional

from app import paths
from app.integrations import etsy_auth, etsy_client
from app.live import ops_state, pipeline
from app.sim import run_simulation

RECOVERABLE_STATES = ("draft", "active")
PAGE_SIZE = 100
MAX_LISTINGS_PER_STATE = 1000

RECOVERY_NOTE = (
    "Imported read-only from your Etsy shop because no local record existed. It is not known whether "
    "this app's agents created it; the original prompt, scores, compliance result, approval history, "
    "local artwork and Printful mapping are unknown. Not publishable or fulfillable from this app."
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# --- storage diagnostics ---------------------------------------------------

def _json_item(label: str, path: Path, expected: type) -> dict:
    item = {"label": label, "path": str(path), "exists": path.exists(), "count": None}
    if not path.exists():
        return dict(item, status="missing", detail="Not found (nothing saved yet, or the file was lost).")
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        return dict(item, status="invalid", detail=f"Unreadable ({type(e).__name__}: {e}); left untouched.")
    if not isinstance(data, expected):
        return dict(item, status="invalid", detail=f"Unexpected format (expected a JSON {expected.__name__}).")
    return dict(item, status="ok", count=len(data), detail="Readable.")


def storage_diagnostics() -> dict:
    """Presence/count/path checks for the files Live Ops depends on. The
    token file is checked for existence only — it is never opened."""
    images_dir = Path(pipeline.IMAGES_DIR)
    pngs = sorted(images_dir.glob("*.png")) if images_dir.is_dir() else []
    items = [
        _json_item("Live listing registry", Path(pipeline.PENDING_APPROVALS_PATH), list),
        _json_item("Image manifest", Path(pipeline.IMAGE_MANIFEST_PATH), list),
        {
            "label": "Generated images (*.png)",
            "path": str(images_dir),
            "exists": images_dir.is_dir(),
            "count": len(pngs),
            "status": "ok" if images_dir.is_dir() else "missing",
            "detail": "Directory found." if images_dir.is_dir() else "Directory not found.",
        },
        _json_item("Etsy shop config", Path(run_simulation.ETSY_CONFIG_PATH), dict),
        _json_item("Live Ops console history", Path(ops_state.STATE_PATH), dict),
        {
            "label": "Etsy OAuth token file",
            "path": str(etsy_auth.ETSY_TOKENS_PATH),
            "exists": etsy_auth.token_file_status() == "present",
            "count": None,
            "status": etsy_auth.token_file_status(),
            "detail": "Existence only — contents are never read or shown here.",
        },
    ]
    notes = []
    if paths.DATA_DIR != paths.DEFAULT_DATA_DIR:
        notes.append(f"{paths.DATA_DIR_ENV} is set: data is read from {paths.DATA_DIR} instead of the default "
                     f"{paths.DEFAULT_DATA_DIR}.")
        if paths.DEFAULT_DATA_DIR.is_dir() and any(paths.DEFAULT_DATA_DIR.iterdir()):
            notes.append(f"Files also exist in the default {paths.DEFAULT_DATA_DIR}. They were NOT moved or "
                         "merged; copy them yourself if they belong to this shop.")
    if paths.SECRETS_DIR != paths.DEFAULT_SECRETS_DIR:
        notes.append(f"{paths.SECRETS_DIR_ENV} is set: the Etsy token file is read from {paths.SECRETS_DIR}.")
    return {"data_dir": str(paths.DATA_DIR), "secrets_dir": str(paths.SECRETS_DIR), "items": items, "notes": notes}


# --- read-only Etsy reconciliation -----------------------------------------

def _money(price) -> Optional[float]:
    if isinstance(price, dict) and price.get("amount") is not None and price.get("divisor"):
        try:
            return round(float(price["amount"]) / float(price["divisor"]), 2)
        except (TypeError, ValueError, ZeroDivisionError):
            return None
    return None


def _known_keys(registry: List[dict]) -> set:
    return {
        (str(e.get("etsy_shop_id")), str(e.get("etsy_listing_id")))
        for e in registry if e.get("etsy_listing_id") is not None
    }


def preview_etsy_listings(states: Iterable[str] = RECOVERABLE_STATES,
                          max_per_state: int = MAX_LISTINGS_PER_STATE) -> dict:
    """Explicit, user-triggered, read-only: lists the connected shop's
    listings that have NO local registry record. Writes nothing."""
    registry = pipeline.list_all()  # raises LocalStoreError rather than comparing against an unreadable file
    me = etsy_client.get_me()
    shop_id = me["shop_id"]
    known = _known_keys(registry)
    other_shops = sorted({
        str(e["etsy_shop_id"]) for e in registry
        if e.get("etsy_shop_id") not in (None, "") and str(e["etsy_shop_id"]) != str(shop_id)
    })
    candidates, seen, already, truncated = [], set(), 0, False
    for state in states:
        offset = 0
        while True:
            if offset >= max_per_state:
                truncated = True
                break
            page = etsy_client.get_shop_listings(shop_id, state=state, limit=PAGE_SIZE, offset=offset)
            results = page.get("results") or []
            for listing in results:
                listing_id = listing.get("listing_id")
                # Never accept a listing that Etsy reports under a different shop.
                if listing_id is None or str(listing.get("shop_id", shop_id)) != str(shop_id):
                    continue
                key = (str(shop_id), str(listing_id))
                if key in known:
                    already += 1
                    continue
                if key in seen:
                    continue
                seen.add(key)
                candidates.append({
                    "etsy_listing_id": listing_id,
                    "etsy_shop_id": shop_id,
                    "etsy_state": str(listing.get("state") or state),
                    "title": str(listing.get("title") or "")[:140],
                    "price": _money(listing.get("price")),
                    "url": listing.get("url"),
                })
            offset += len(results)
            if not results or offset >= int(page.get("count") or 0):
                break
    return {
        "shop_id": shop_id,
        "previewed_at": _now(),
        "candidates": candidates,
        "already_recorded": already,
        "other_shop_ids_in_registry": other_shops,
        "truncated": truncated,
    }


def import_recovered_listings(preview: dict, listing_ids: Iterable) -> List[dict]:
    """Local-only, confirmed import of selected preview candidates as
    ``recovered_unverified`` registry records. Deduplicates against the
    current registry by Etsy shop + listing ID, so existing records
    (including locally rejected ones) are never touched."""
    if preview.get("other_shop_ids_in_registry"):
        raise ValueError(
            "The local registry already has records from a different Etsy shop "
            f"({', '.join(preview['other_shop_ids_in_registry'])}); refusing to mix shops. "
            "Reconnect the original shop, or back up and move the registry aside first."
        )
    selected = {str(i) for i in listing_ids}
    known = _known_keys(pipeline.list_all())
    imported = []
    for c in preview.get("candidates") or []:
        if str(c.get("etsy_listing_id")) not in selected or str(c.get("etsy_shop_id")) != str(preview.get("shop_id")):
            continue
        key = (str(c["etsy_shop_id"]), str(c["etsy_listing_id"]))
        if key in known:
            continue
        known.add(key)
        imported.append({
            "design_id": f"ETSY-{c['etsy_listing_id']}",
            "niche": None,
            "product_type": None,
            "price": c.get("price"),
            "prompt": None,
            "image_uri": None,
            "etsy_listing_id": c["etsy_listing_id"],
            "etsy_shop_id": c["etsy_shop_id"],
            "etsy_image_url": None,
            "mockup_image_url": None,
            "mockup_image_uri": None,
            "etsy_flat_image_id": None,
            "printful_sync_product": None,
            "status": pipeline.RECOVERED_UNVERIFIED,
            "published_by": None,
            "compliance_status": None,
            "source": "etsy_recovery",
            "recovered": {
                "method": "etsy_read_only_listing_lookup",
                "previewed_at": preview.get("previewed_at"),
                "imported_at": _now(),
                "etsy_state": c.get("etsy_state"),
                "etsy_title": c.get("title"),
                "etsy_url": c.get("url"),
                "agent_ownership": "unknown",
                "note": RECOVERY_NOTE,
            },
        })
    if imported:
        pipeline._upsert_entries(imported)
    return imported
