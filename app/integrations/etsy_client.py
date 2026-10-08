"""Thin REST wrapper around Etsy Open API v3.

Only the calls needed by the live pipeline are implemented: identify the
shop, list shipping profiles, upload images, create draft listings, publish
listings, and fetch receipts (orders). All requests require a valid OAuth
access token (see etsy_auth.py).
"""
from __future__ import annotations

from typing import Dict, List, Optional

import requests

from app.integrations.config import ETSY_API_KEY, ETSY_SHARED_SECRET, NotConfiguredError
from app.integrations import etsy_auth

BASE_URL = "https://openapi.etsy.com/v3/application"


def _headers() -> Dict[str, str]:
    if not ETSY_API_KEY or not ETSY_SHARED_SECRET:
        raise NotConfiguredError("ETSY_API_KEY and ETSY_SHARED_SECRET must both be set.")
    return {
        # As of Feb 2026, Etsy requires "keystring:shared_secret" in x-api-key
        # (the keystring alone is no longer accepted).
        "x-api-key": f"{ETSY_API_KEY}:{ETSY_SHARED_SECRET}",
        "Authorization": f"Bearer {etsy_auth.get_valid_access_token()}",
    }


def _get(path: str, params: Optional[dict] = None) -> dict:
    resp = requests.get(f"{BASE_URL}{path}", headers=_headers(), params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


def _post(path: str, json_body: Optional[dict] = None, files=None, data=None) -> dict:
    headers = _headers()
    resp = requests.post(f"{BASE_URL}{path}", headers=headers, json=json_body, files=files, data=data, timeout=30)
    resp.raise_for_status()
    return resp.json()


def _put(path: str, json_body: Optional[dict] = None) -> dict:
    resp = requests.put(f"{BASE_URL}{path}", headers=_headers(), json=json_body, timeout=30)
    resp.raise_for_status()
    return resp.json()


def get_me() -> dict:
    """Returns the authenticated Etsy user's id and their shop.

    Etsy's token response doesn't include user_id, and `/users/me` requires a
    `profile_r` scope we don't request (we only need shop/listing/transaction
    scopes). Instead, the user_id is parsed from the access token itself
    (Etsy formats it as "<user_id>.<token>"), and the shop is looked up via
    `/users/{user_id}/shops`, which only needs the `shops_r` scope we have.
    """
    access_token = etsy_auth.get_valid_access_token()
    user_id = access_token.split(".", 1)[0]
    shop = _get(f"/users/{user_id}/shops")
    return {"user_id": int(user_id), "shop_id": shop.get("shop_id"), "shop": shop}


def get_shop(shop_id: int) -> dict:
    return _get(f"/shops/{shop_id}")


def get_shipping_profiles(shop_id: int) -> List[dict]:
    return _get(f"/shops/{shop_id}/shipping-profiles").get("results", [])


def create_draft_listing(shop_id: int, listing: dict) -> dict:
    """Creates a new listing in draft (unpublished) state.

    `listing` should include at least: quantity, title, description, price,
    who_made, when_made, taxonomy_id, shipping_profile_id. state defaults to
    'draft' server-side unless explicitly set to 'active'.
    """
    body = dict(listing)
    body.setdefault("state", "draft")
    return _post(f"/shops/{shop_id}/listings", json_body=body)


def upload_listing_image(shop_id: int, listing_id: int, image_path: str, rank: int = 1) -> dict:
    with open(image_path, "rb") as f:
        files = {"image": f}
        data = {"rank": str(rank)}
        return _post(
            f"/shops/{shop_id}/listings/{listing_id}/images",
            files=files,
            data=data,
        )


def publish_listing(shop_id: int, listing_id: int) -> dict:
    """Flips a draft listing to 'active' (publicly visible). This is the
    action that must only ever follow explicit human approval."""
    return _put(f"/shops/{shop_id}/listings/{listing_id}", json_body={"state": "active"})


def get_shop_receipts(shop_id: int, was_paid: bool = True, limit: int = 25) -> List[dict]:
    return _get(
        f"/shops/{shop_id}/receipts",
        params={"was_paid": str(was_paid).lower(), "limit": limit},
    ).get("results", [])
