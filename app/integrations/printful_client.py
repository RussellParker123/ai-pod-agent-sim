"""Printful API client — fulfillment (real printing + shipping).

Printful is what actually prints the mugs/t-shirts and ships them to the
buyer once an Etsy order comes in; Etsy itself never touches the physical
product. Implemented against the Printful v1 REST API.

Fully implemented now; every call raises NotConfiguredError until
PRINTFUL_API_KEY is set (the user plans to add it later), rather than
silently no-op'ing.
"""
from __future__ import annotations

import time
from typing import Dict, List, Optional

import requests

from app.integrations.config import NotConfiguredError, PRINTFUL_API_KEY

BASE_URL = "https://api.printful.com"


def is_configured() -> bool:
    return bool(PRINTFUL_API_KEY)


def _headers() -> Dict[str, str]:
    if not PRINTFUL_API_KEY:
        raise NotConfiguredError(
            "PRINTFUL_API_KEY is not set. Add it to your .env to enable real print "
            "fulfillment and shipping."
        )
    return {"Authorization": f"Bearer {PRINTFUL_API_KEY}"}


def _get(path: str, params: Optional[dict] = None) -> dict:
    resp = requests.get(f"{BASE_URL}{path}", headers=_headers(), params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


def _post(path: str, json_body: dict) -> dict:
    resp = requests.post(f"{BASE_URL}{path}", headers=_headers(), json=json_body, timeout=30)
    resp.raise_for_status()
    return resp.json()


def _post_with_retry(path: str, json_body: dict, max_retries: int = 3) -> dict:
    """Like _post, but retries on 429 (Printful's mockup-generator endpoint
    in particular has an aggressive rate limit -- a few requests in quick
    succession, e.g. refreshing several designs in a row, reliably triggers
    one) with a short backoff instead of failing the whole call outright."""
    for attempt in range(max_retries + 1):
        resp = requests.post(f"{BASE_URL}{path}", headers=_headers(), json=json_body, timeout=30)
        if resp.status_code == 429 and attempt < max_retries:
            time.sleep(10 * (attempt + 1))
            continue
        resp.raise_for_status()
        return resp.json()
    return {}


def _put(path: str, json_body: dict) -> dict:
    resp = requests.put(f"{BASE_URL}{path}", headers=_headers(), json=json_body, timeout=30)
    resp.raise_for_status()
    return resp.json()


def get_sync_product(sync_product_id: int) -> dict:
    """Returns {"sync_product": {...}, "sync_variants": [...]} for a given
    sync product id (the id stored locally in pending_approvals.json)."""
    return _get(f"/sync/products/{sync_product_id}").get("result", {})


def set_sync_variant_files(sync_variant_id: int, default_url: str, preview_url: Optional[str] = None) -> dict:
    """Re-sets a sync variant's files. IMPORTANT: PUT /sync/variant/{id}
    *replaces* the entire files array rather than merging it, so this
    always re-sends the "default" (print) file alongside the "preview"
    (product photo) file -- sending the preview alone would silently wipe
    out the print file Printful actually prints from.

    Note: Printful's API does not appear to durably honor an externally
    supplied "preview" file as the sync product's visible thumbnail (it
    gets accepted, processed, but ends up with visible=False and doesn't
    update the product-level thumbnail_url) -- this is a known Printful
    platform limitation when integrating via the Ecommerce Platform Sync
    API rather than their embedded designer. The buyer-facing photo that
    actually matters is the one uploaded directly to the Etsy listing
    gallery (see etsy_client.upload_listing_image); this call is kept as a
    best-effort mirror so Printful's own dashboard has *some* reference to
    the real product photo, even if it won't show as the primary thumbnail."""
    files = [{"type": "default", "url": default_url}]
    if preview_url:
        files.append({"type": "preview", "url": preview_url, "visible": True})
    return _put(f"/sync/variant/{sync_variant_id}", {"files": files}).get("result", {})


def list_catalog_products(category_id: Optional[int] = None) -> List[dict]:
    params = {"category_id": category_id} if category_id else None
    return _get("/products", params=params).get("result", [])


def get_catalog_variant(variant_id: int) -> dict:
    return _get(f"/products/variant/{variant_id}").get("result", {})


def create_sync_product(
    name: str, variant_id: int, image_url: str, retail_price: str, preview_image_url: Optional[str] = None
) -> dict:
    """Creates a Printful "sync product" (one product with the generated art
    applied to a specific blank, e.g. an 11oz mug or a t-shirt variant).

    `image_url` is the flat print file (required, type="default"). Pass the
    already-rendered product mockup as `preview_image_url` so Printful shows
    an actual product photo (type="preview") instead of leaving it blank —
    without this, Printful's own store page shows no photo for the product
    even though the print file itself uploaded fine, since "default" files
    are the print artwork, not a display photo."""
    files = [{"type": "default", "url": image_url}]
    if preview_image_url:
        files.append({"type": "preview", "url": preview_image_url})
    body = {
        "sync_product": {"name": name},
        "sync_variants": [
            {
                "retail_price": retail_price,
                "variant_id": variant_id,
                "files": files,
            }
        ],
    }
    return _post("/store/products", body).get("result", {})


def get_variant_printfile(product_id: int, variant_id: int) -> dict:
    """Returns the print-area dimensions (placement -> printfile_id -> width/
    height in px) for a given catalog product/variant, needed to position an
    image correctly when requesting a mockup."""
    data = _get(f"/mockup-generator/printfiles/{product_id}").get("result", {})
    printfiles = {p["printfile_id"]: p for p in data.get("printfiles", [])}
    placements = {"default": {}}
    for vp in data.get("variant_printfiles", []):
        if vp["variant_id"] == variant_id:
            placements = vp.get("placements", {})
            break
    resolved = {}
    for placement, printfile_id in placements.items():
        pf = printfiles.get(printfile_id, {})
        resolved[placement] = {"width": pf.get("width"), "height": pf.get("height")}
    return resolved


def generate_mockup(
    product_id: int,
    variant_id: int,
    image_url: str,
    placement: Optional[str] = None,
    poll_timeout: int = 45,
) -> Optional[str]:
    """Generates a realistic product photo (e.g. the design wrapped onto a
    real mug render) via Printful's Mockup Generator API, so Etsy buyers see
    the actual product instead of just the flat printed artwork. Returns a
    temporary (few-hours-lived) image URL for the finished mockup, or None
    if anything about generation fails -- callers should treat this as
    best-effort and fall back to the flat design image.

    `placement` defaults to whatever this product's printfiles report
    (e.g. mugs only have "default"; totes/t-shirts have "front"/"back"/etc
    instead -- there's no "default" placement for those at all). Pass an
    explicit placement to override. This must match the *resolved* key sent
    to Printful's task-create call -- previously this always sent the
    literal placement param even when the printfile lookup fell back to a
    different key, which silently failed mockup generation for every
    product type except mugs (where the keys happened to coincide).

    This is a two-step async API: create a task, then poll for its result.
    """
    try:
        printfiles = get_variant_printfile(product_id, variant_id)
        if not printfiles:
            return None
        resolved_placement = placement if placement in printfiles else next(iter(printfiles), None)
        if not resolved_placement:
            return None
        area = printfiles[resolved_placement]
        width, height = area.get("width"), area.get("height")
        file_entry = {"placement": resolved_placement, "image_url": image_url}
        if width and height:
            file_entry["position"] = {
                "area_width": width,
                "area_height": height,
                "width": width,
                "height": height,
                "top": 0,
                "left": 0,
            }
        task = _post_with_retry(
            f"/mockup-generator/create-task/{product_id}",
            {"variant_ids": [variant_id], "format": "jpg", "files": [file_entry]},
        ).get("result", {})
        task_key = task.get("task_key")
        if not task_key:
            return None

        deadline = time.time() + poll_timeout
        while time.time() < deadline:
            result = _get("/mockup-generator/task", {"task_key": task_key}).get("result", {})
            status = result.get("status")
            if status == "completed":
                mockups = result.get("mockups", [])
                return mockups[0]["mockup_url"] if mockups else None
            if status == "failed":
                return None
            time.sleep(2)
        return None
    except Exception:
        return None


def create_order_from_receipt(
    recipient: Dict,
    items: List[Dict],
    etsy_receipt_id: int,
    confirm: bool = False,
) -> dict:
    """Places a real Printful order (this is the action that spends real
    money and triggers an actual print + ship). Only ever call this against
    a confirmed, paid Etsy receipt.

    `recipient`: {name, address1, city, state_code, country_code, zip, email}
    `items`: [{"sync_variant_id": int, "quantity": int}, ...]
    `confirm`: if False (default), creates a draft order you must manually
    confirm in the Printful dashboard/API before it's fulfilled — an extra
    safety margin on top of the Etsy human-approval gate.
    """
    body = {
        "recipient": recipient,
        "items": items,
        "external_id": f"etsy-receipt-{etsy_receipt_id}",
        "confirm": confirm,
    }
    return _post("/orders", body).get("result", {})


def get_order_status(order_id: int) -> dict:
    return _get(f"/orders/{order_id}").get("result", {})
