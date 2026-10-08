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


def _raise_for_status(resp: requests.Response) -> None:
    """Like resp.raise_for_status(), but includes Etsy's JSON error body
    (e.g. {"error": "invalid_taxonomy_id", ...}) in the exception message
    instead of swallowing it — Etsy's 400s are almost always a validation
    error on one specific field, and the generic requests message alone
    ("400 Client Error: Bad Request for url: ...") gives no way to tell
    which one."""
    if resp.ok:
        return
    detail = ""
    try:
        detail = f" | Etsy response: {resp.json()}"
    except ValueError:
        detail = f" | Etsy response: {resp.text[:500]}"
    raise requests.HTTPError(f"{resp.status_code} {resp.reason} for url: {resp.url}{detail}", response=resp)


def _get(path: str, params: Optional[dict] = None) -> dict:
    resp = requests.get(f"{BASE_URL}{path}", headers=_headers(), params=params, timeout=30)
    _raise_for_status(resp)
    return resp.json()


def _post(path: str, json_body: Optional[dict] = None, files=None, data=None, params: Optional[dict] = None) -> dict:
    headers = _headers()
    resp = requests.post(
        f"{BASE_URL}{path}", headers=headers, json=json_body, files=files, data=data, params=params, timeout=30
    )
    _raise_for_status(resp)
    return resp.json()


def _patch(path: str, json_body: Optional[dict] = None) -> dict:
    resp = requests.patch(f"{BASE_URL}{path}", headers=_headers(), json=json_body, timeout=30)
    _raise_for_status(resp)
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


def update_shop(
    shop_id: int,
    title: Optional[str] = None,
    announcement: Optional[str] = None,
    sale_message: Optional[str] = None,
    digital_sale_message: Optional[str] = None,
) -> dict:
    """Updates shop text fields via PUT /shops/{shop_id}.

    Etsy's Open API v3 only exposes these four shop fields for writing.
    There is no endpoint for the shop icon, banner image, "shop story", or
    seller/about photo — those are web-UI-only features with no API
    equivalent, confirmed against Etsy's official docs and by inspecting
    this shop's own (all-null) image fields via get_shop().
    """
    body = {
        k: v
        for k, v in {
            "title": title,
            "announcement": announcement,
            "sale_message": sale_message,
            "digital_sale_message": digital_sale_message,
        }.items()
        if v is not None
    }
    if not body:
        raise ValueError("update_shop() requires at least one field to update")
    # Etsy's updateShop endpoint takes PUT, not PATCH, despite being a
    # partial update (confirmed live: PATCH returns 404, PUT returns 200).
    resp = requests.put(f"{BASE_URL}/shops/{shop_id}", headers=_headers(), json=body, timeout=30)
    _raise_for_status(resp)
    return resp.json()


def get_shipping_profiles(shop_id: int) -> List[dict]:
    return _get(f"/shops/{shop_id}/shipping-profiles").get("results", [])


def create_shipping_profile(
    shop_id: int,
    origin_postal_code: str,
    title: str = "Free US Shipping",
    primary_cost: float = 0.0,
    secondary_cost: float = 0.0,
    min_processing_time: int = 2,
    max_processing_time: int = 5,
    min_delivery_days: int = 5,
    max_delivery_days: int = 8,
) -> dict:
    """Creates a new "manual" (flat-rate) shipping profile with a real US
    domestic destination. Always use "manual", not "calculated" —
    calculated profiles need a carrier_id + mail_class to have a valid
    domestic option, can't be edited via the API once created (confirmed
    live: PUT on a calculated profile's destination returns 400 "You
    cannot make updates to calculated shipping profiles"), and a
    misconfigured one (e.g. destination_country_iso left blank) causes
    draft-listing creation to fail with shipping_profile_no_domestic_option
    on item_weight/item_length with no way to repair it after the fact."""
    return _post(
        f"/shops/{shop_id}/shipping-profiles",
        json_body={
            "title": title,
            "origin_country_iso": "US",
            "origin_postal_code": origin_postal_code,
            "primary_cost": primary_cost,
            "secondary_cost": secondary_cost,
            "min_processing_time": min_processing_time,
            "max_processing_time": max_processing_time,
            "processing_time_unit": "business_days",
            "destination_country_iso": "US",
            "min_delivery_days": min_delivery_days,
            "max_delivery_days": max_delivery_days,
        },
    )


def _has_valid_domestic_destination(profile: dict) -> bool:
    for dest in profile.get("shipping_profile_destinations", []):
        if dest.get("destination_country_iso") != "US":
            continue
        if profile.get("profile_type") == "calculated":
            # Calculated (carrier-rate) profiles additionally need a real
            # carrier + mail class to compute a domestic rate at all.
            if dest.get("shipping_carrier_id") and dest.get("mail_class"):
                return True
            continue
        return True
    return False


def get_or_create_domestic_shipping_profile_id(shop_id: int) -> int:
    """Reuses an existing shipping profile that has a genuinely usable US
    domestic destination, otherwise creates a fresh "manual" free-shipping
    one. Picking profiles[0] blindly (the old behavior) breaks as soon as
    that profile is a "calculated" one without a carrier configured —
    which looks fine in get_shipping_profiles() but makes every new draft
    listing fail validation on item_weight/item_length."""
    profiles = get_shipping_profiles(shop_id)
    for profile in profiles:
        if _has_valid_domestic_destination(profile):
            return profile["shipping_profile_id"]
    origin_postal_code = profiles[0]["origin_postal_code"] if profiles else None
    if not origin_postal_code:
        raise RuntimeError(
            "Your Etsy shop has no shipping profiles yet, and no origin postal "
            "code is on file to create one. Create a shipping profile in the "
            "Etsy seller dashboard before running the live pipeline."
        )
    created = create_shipping_profile(shop_id, origin_postal_code=origin_postal_code)
    return created["shipping_profile_id"]


def get_readiness_state_definitions(shop_id: int) -> List[dict]:
    """Etsy's newer "processing profiles" system: every *physical* listing
    now requires a readiness_state_id (in addition to shipping_profile_id),
    which replaces the old per-listing min/max processing-time fields. See
    https://developers.etsy.com/documentation/tutorials/migration/"""
    return _get(f"/shops/{shop_id}/readiness-state-definitions").get("results", [])


def create_readiness_state_definition(
    shop_id: int,
    readiness_state: str = "made_to_order",
    min_processing_time: int = 2,
    max_processing_time: int = 5,
    processing_time_unit: str = "days",
) -> dict:
    """Creates a new processing profile for the shop and returns it
    (including the readiness_state_id needed by create_draft_listing)."""
    return _post(
        f"/shops/{shop_id}/readiness-state-definitions",
        json_body={
            "readiness_state": readiness_state,
            "min_processing_time": min_processing_time,
            "max_processing_time": max_processing_time,
            "processing_time_unit": processing_time_unit,
        },
    )


def get_or_create_readiness_state_id(shop_id: int, readiness_state: str = "made_to_order") -> int:
    """Reuses an existing processing profile matching `readiness_state` if
    the shop already has one (e.g. set up manually in Shop Manager),
    otherwise creates a fresh one. Print-on-demand items are always
    produced after the order comes in, so "made_to_order" is the correct
    state for everything this pipeline lists."""
    for profile in get_readiness_state_definitions(shop_id):
        if profile.get("readiness_state") == readiness_state:
            return profile["readiness_state_id"]
    created = create_readiness_state_definition(shop_id, readiness_state=readiness_state)
    return created["readiness_state_id"]


def get_return_policies(shop_id: int) -> List[dict]:
    return _get(f"/shops/{shop_id}/policies/return").get("results", [])


def create_return_policy(shop_id: int, accepts_returns: bool = True, accepts_exchanges: bool = True, return_deadline: int = 30) -> dict:
    return _post(
        f"/shops/{shop_id}/policies/return",
        json_body={
            "accepts_returns": accepts_returns,
            "accepts_exchanges": accepts_exchanges,
            "return_deadline": return_deadline,
        },
    )


def get_or_create_return_policy_id(shop_id: int) -> int:
    """return_policy_id isn't required to *create* a draft listing, but
    Etsy rejects publishing (state -> active) any physical listing without
    one — see "How it's made" > "Returns and exchanges" in the listing
    editor. Reuses the shop's existing policy if set, otherwise creates a
    standard 30-day returns-and-exchanges policy (matches the "Simple
    policy" default Etsy itself suggests)."""
    policies = get_return_policies(shop_id)
    if policies:
        return policies[0]["return_policy_id"]
    created = create_return_policy(shop_id)
    return created["return_policy_id"]


def create_draft_listing(shop_id: int, listing: dict) -> dict:
    """Creates a new listing in draft (unpublished) state.

    `listing` should include at least: quantity, title, description, price,
    who_made, when_made, taxonomy_id, shipping_profile_id, readiness_state_id
    (required for physical listings under Etsy's processing-profiles system
    — see get_or_create_readiness_state_id). state defaults to 'draft'
    server-side unless explicitly set to 'active'.

    `legacy=false` is required on this request while readiness_state_id is
    in play; Etsy rejects legacy processing-time params together with it.
    """
    body = dict(listing)
    body.setdefault("state", "draft")
    return _post(f"/shops/{shop_id}/listings", json_body=body, params={"legacy": "false"})


def upload_listing_image(shop_id: int, listing_id: int, image_path: str, rank: int = 1) -> dict:
    with open(image_path, "rb") as f:
        files = {"image": f}
        data = {"rank": str(rank)}
        return _post(
            f"/shops/{shop_id}/listings/{listing_id}/images",
            files=files,
            data=data,
        )


def get_listing_images(listing_id: int) -> List[dict]:
    return _get(f"/listings/{listing_id}/images").get("results", [])


def reorder_listing_image(shop_id: int, listing_id: int, listing_image_id: int, rank: int) -> dict:
    """Moves an already-uploaded listing image to a new gallery position.
    Unlike upload_listing_image, this doesn't attach a new file -- Etsy's
    addListingImage endpoint also accepts an existing listing_image_id to
    reorder it in place (passing a bare `rank` to a *new* upload does not
    push other images down; the image to move must be targeted explicitly)."""
    return _post(
        f"/shops/{shop_id}/listings/{listing_id}/images",
        data={"listing_image_id": listing_image_id, "rank": rank},
    )


def publish_listing(shop_id: int, listing_id: int, return_policy_id: Optional[int] = None) -> dict:
    """Flips a draft listing to 'active' (publicly visible). This is the
    action that must only ever follow explicit human approval.

    return_policy_id is required by Etsy to activate any physical listing.
    Pass it to backfill it on listings staged before this field existed in
    the draft-creation call (older pending entries) -- harmless to include
    even when the draft already has one."""
    body = {"state": "active"}
    if return_policy_id is not None:
        body["return_policy_id"] = return_policy_id
    return _patch(f"/shops/{shop_id}/listings/{listing_id}", json_body=body)


def get_shop_receipts(shop_id: int, was_paid: bool = True, limit: int = 25) -> List[dict]:
    return _get(
        f"/shops/{shop_id}/receipts",
        params={"was_paid": str(was_paid).lower(), "limit": limit},
    ).get("results", [])
