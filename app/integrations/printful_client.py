"""Printful API client — fulfillment (real printing + shipping).

Printful is what actually prints the mugs/t-shirts and ships them to the
buyer once an Etsy order comes in; Etsy itself never touches the physical
product. Implemented against the Printful v1 REST API.

Fully implemented now; every call raises NotConfiguredError until
PRINTFUL_API_KEY is set (the user plans to add it later), rather than
silently no-op'ing.
"""
from __future__ import annotations

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
