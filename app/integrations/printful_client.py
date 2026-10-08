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


def list_catalog_products(category_id: Optional[int] = None) -> List[dict]:
    params = {"category_id": category_id} if category_id else None
    return _get("/products", params=params).get("result", [])


def get_catalog_variant(variant_id: int) -> dict:
    return _get(f"/products/variant/{variant_id}").get("result", {})


def create_sync_product(name: str, variant_id: int, image_url: str, retail_price: str) -> dict:
    """Creates a Printful "sync product" (one product with the generated art
    applied to a specific blank, e.g. an 11oz mug or a t-shirt variant)."""
    body = {
        "sync_product": {"name": name},
        "sync_variants": [
            {
                "retail_price": retail_price,
                "variant_id": variant_id,
                "files": [{"url": image_url}],
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
    placement: str = "default",
    poll_timeout: int = 45,
) -> Optional[str]:
    """Generates a realistic product photo (e.g. the design wrapped onto a
    real mug render) via Printful's Mockup Generator API, so Etsy buyers see
    the actual product instead of just the flat printed artwork. Returns a
    temporary (few-hours-lived) image URL for the finished mockup, or None
    if anything about generation fails -- callers should treat this as
    best-effort and fall back to the flat design image.

    This is a two-step async API: create a task, then poll for its result.
    """
    try:
        printfiles = get_variant_printfile(product_id, variant_id)
        area = printfiles.get(placement) or next(iter(printfiles.values()), {})
        width, height = area.get("width"), area.get("height")
        file_entry = {"placement": placement, "image_url": image_url}
        if width and height:
            file_entry["position"] = {
                "area_width": width,
                "area_height": height,
                "width": width,
                "height": height,
                "top": 0,
                "left": 0,
            }
        task = _post(
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
