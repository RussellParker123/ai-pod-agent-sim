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


def _put(path: str, json_body: dict) -> dict:
    resp = requests.put(f"{BASE_URL}{path}", headers=_headers(), json=json_body, timeout=30)
    resp.raise_for_status()
    return resp.json()


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
    placements = {"default": None}
    for vp in data.get("variant_printfiles", []):
        if vp["variant_id"] == variant_id:
            placements = vp.get("placements", {})
            break
    resolved = {}
    for placement, printfile_id in placements.items():
        pf = printfiles.get(printfile_id, {})
        resolved[placement] = {
            "width": pf.get("width"),
            "height": pf.get("height"),
            "fill_mode": pf.get("fill_mode"),
        }
    return resolved


def _pick_placement(printfiles: dict, requested: str) -> str:
    """Uses the requested placement when the variant has it; otherwise falls
    back to the product's main print side. Apparel and totes have no
    "default" placement — their main side is "front" (other placements like
    "back"/"label_outside"/"sleeve_left" must never be picked by accident)."""
    if requested in printfiles or not printfiles:
        return requested
    for candidate in ("front", "default"):
        if candidate in printfiles:
            return candidate
    return next(iter(printfiles))


def _image_position(area: dict) -> Optional[dict]:
    """Where the (square, 1024x1024) generated art sits in the print area.
    "cover" areas (e.g. mug wraps) are filled edge to edge, as before. "fit"
    areas (t-shirts, totes) get the art scaled to fit and centered, like
    Printful's own shirt mockup example, instead of being stretched to the
    area's portrait aspect ratio."""
    width, height = area.get("width"), area.get("height")
    if not (width and height):
        return None
    position = {"area_width": width, "area_height": height, "width": width, "height": height, "top": 0, "left": 0}
    if area.get("fill_mode") == "fit" and width != height:
        side = min(width, height)
        position.update(width=side, height=side, top=(height - side) // 2, left=(width - side) // 2)
    return position


def _retry_after(exc: Exception) -> Optional[float]:
    """Seconds to wait if `exc` is a Printful 429 rate-limit response (the
    mockup generator is rate limited much more tightly than the rest of the
    API, so back-to-back listings hit it), else None."""
    resp = getattr(exc, "response", None)
    if resp is None or getattr(resp, "status_code", None) != 429:
        return None
    try:
        return max(1.0, float(resp.headers.get("Retry-After", 10)))
    except (TypeError, ValueError):
        return 10.0


def generate_mockup(
    product_id: int,
    variant_id: int,
    image_url: str,
    placement: str = "default",
    poll_timeout: int = 180,
    poll_interval: float = 3,
) -> Optional[str]:
    """Generates a realistic product photo (e.g. the design wrapped onto a
    real mug render) via Printful's Mockup Generator API, so Etsy buyers see
    the actual product instead of just the flat printed artwork. Returns a
    temporary (few-hours-lived) image URL for the finished mockup, or None
    if anything about generation fails -- callers should treat this as
    best-effort and fall back to the flat design image.

    This is a two-step async API: create a task, then poll for its result.
    Apparel/tote mockups take much longer than mugs, so the default wait
    matches Printful's own SDK (180s); 429 rate limits are retried rather
    than treated as failures.
    """
    try:
        printfiles = get_variant_printfile(product_id, variant_id)
        placement = _pick_placement(printfiles, placement)
        file_entry = {"placement": placement, "image_url": image_url}
        position = _image_position(printfiles.get(placement, {}))
        if position:
            file_entry["position"] = position
        body = {"variant_ids": [variant_id], "format": "jpg", "files": [file_entry]}

        deadline = time.time() + poll_timeout
        task_key = None
        while task_key is None:
            try:
                task = _post(f"/mockup-generator/create-task/{product_id}", body).get("result", {})
            except Exception as exc:
                wait = _retry_after(exc)
                if wait is None or time.time() + wait >= deadline:
                    return None
                time.sleep(wait)
                continue
            task_key = task.get("task_key")
            if not task_key:
                return None

        while time.time() < deadline:
            try:
                result = _get("/mockup-generator/task", {"task_key": task_key}).get("result", {})
            except Exception as exc:
                wait = _retry_after(exc)
                if wait is None:
                    return None
                time.sleep(min(wait, max(0.0, deadline - time.time())))
                continue
            status = result.get("status")
            if status == "completed":
                mockups = result.get("mockups", [])
                chosen = next((m for m in mockups if m.get("placement") == placement), mockups[0] if mockups else None)
                return chosen.get("mockup_url") if chosen else None
            if status == "failed":
                return None
            time.sleep(poll_interval)
        return None
    except Exception:
        return None


def set_sync_product_preview(sync_product_id: int, image_url: str, preview_image_url: str) -> List[dict]:
    """Backfills the product photo on an already-created sync product (one
    staged before its mockup existed), keeping `image_url` as the print
    file. Returns the updated sync variants."""
    variants = _get(f"/store/products/{sync_product_id}").get("result", {}).get("sync_variants", [])
    files = [{"type": "default", "url": image_url}, {"type": "preview", "url": preview_image_url}]
    return [_put(f"/store/variants/{v['id']}", {"files": files}).get("result", {}) for v in variants]


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
