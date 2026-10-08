"""Minimal Etsy Open API v3 client (OAuth 2.0 bearer token auth)."""
import os
import time
import logging
from typing import Any, Dict, List, Optional

import requests

try:
    from dotenv import load_dotenv
except ImportError:  # python-dotenv is optional at import time
    load_dotenv = None

log = logging.getLogger(__name__)

API_BASE = "https://openapi.etsy.com/v3/application"
TOKEN_URL = "https://api.etsy.com/v3/public/oauth/token"


class EtsyError(Exception):
    """Raised for configuration problems or failed Etsy API calls."""


class EtsyClient:
    def __init__(
        self,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        shop_id: Optional[str] = None,
        access_token: Optional[str] = None,
        max_retries: int = 5,
        backoff_base: float = 1.0,
        timeout: float = 30.0,
    ):
        if load_dotenv:
            load_dotenv()
        self.api_key = api_key or os.getenv("ETSY_API_KEY", "")
        self.api_secret = api_secret or os.getenv("ETSY_API_SECRET", "")
        self.shop_id = shop_id or os.getenv("ETSY_SHOP_ID", "")
        self.access_token = access_token or os.getenv("ETSY_ACCESS_TOKEN", "")
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self.timeout = timeout

    def __repr__(self) -> str:  # never expose credentials
        return f"EtsyClient(shop_id={self.shop_id!r}, credentials=<hidden>)"

    def is_configured(self) -> bool:
        return all([self.api_key, self.shop_id, self.access_token])

    def _require_config(self) -> None:
        missing = [
            name
            for name, val in (
                ("ETSY_API_KEY", self.api_key),
                ("ETSY_SHOP_ID", self.shop_id),
                ("ETSY_ACCESS_TOKEN", self.access_token),
            )
            if not val
        ]
        if missing:
            raise EtsyError(f"Missing Etsy credentials: {', '.join(missing)}")

    # --- OAuth 2.0 -------------------------------------------------------
    def refresh_access_token(self, refresh_token: str) -> Dict[str, Any]:
        """Exchange a refresh token for a new access token (OAuth 2.0)."""
        if not self.api_key:
            raise EtsyError("Missing Etsy credentials: ETSY_API_KEY")
        resp = requests.post(
            TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "client_id": self.api_key,
                "refresh_token": refresh_token,
            },
            timeout=self.timeout,
        )
        if not resp.ok:
            raise EtsyError(f"Token refresh failed (HTTP {resp.status_code})")
        data = resp.json()
        self.access_token = data["access_token"]
        return data

    def _headers(self) -> Dict[str, str]:
        key = f"{self.api_key}:{self.api_secret}" if self.api_secret else self.api_key
        return {"x-api-key": key, "Authorization": "Bearer " + self.access_token}

    # --- HTTP with exponential backoff ----------------------------------
    def _request(self, method: str, path: str, **kwargs) -> Dict[str, Any]:
        self._require_config()
        url = f"{API_BASE}{path}"
        for attempt in range(self.max_retries + 1):
            try:
                resp = requests.request(
                    method, url, headers=self._headers(), timeout=self.timeout, **kwargs
                )
            except requests.RequestException as exc:
                if attempt >= self.max_retries:
                    raise EtsyError(f"Network error: {type(exc).__name__}") from exc
                self._sleep(attempt)
                continue
            if resp.status_code == 429 or resp.status_code >= 500:
                if attempt >= self.max_retries:
                    raise EtsyError(f"Etsy API error after retries (HTTP {resp.status_code})")
                retry_after = resp.headers.get("Retry-After")
                self._sleep(attempt, float(retry_after) if retry_after and retry_after.isdigit() else None)
                continue
            if not resp.ok:
                raise EtsyError(f"Etsy API error (HTTP {resp.status_code}): {resp.text[:200]}")
            return resp.json() if resp.content else {}
        raise EtsyError("Etsy request failed")  # pragma: no cover

    def _sleep(self, attempt: int, override: Optional[float] = None) -> None:
        delay = override if override is not None else self.backoff_base * (2 ** attempt)
        log.warning("Etsy request throttled/failed; retrying in %.1fs", delay)
        time.sleep(delay)

    # --- Listings ---------------------------------------------------------
    def create_listing(
        self,
        title: str,
        description: str,
        price: float,
        tags: Optional[List[str]] = None,
        taxonomy_id: int = 1,
        quantity: int = 999,
        state: str = "draft",
        who_made: str = "i_did",
        when_made: str = "made_to_order",
        extra: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Create a listing. Etsy creates drafts; state='active' publishes it."""
        if state not in ("draft", "active"):
            raise ValueError("state must be 'draft' or 'active'")
        data: Dict[str, Any] = {
            "quantity": quantity,
            "title": title[:140],
            "description": description,
            "price": f"{price:.2f}",
            "who_made": who_made,
            "when_made": when_made,
            "taxonomy_id": taxonomy_id,
            "type": "physical",
            "is_supply": "false",
        }
        if tags:
            data["tags"] = ",".join(t[:20] for t in tags[:13])
        if extra:
            data.update(extra)
        listing = self._request("POST", f"/shops/{self.shop_id}/listings", data=data)
        if state == "active":
            listing = self.update_listing(listing["listing_id"], state="active")
        return listing

    def update_listing(self, listing_id: int, **fields: Any) -> Dict[str, Any]:
        return self._request("PATCH", f"/shops/{self.shop_id}/listings/{listing_id}", data=fields)

    def update_price(self, listing_id: int, price: float) -> Dict[str, Any]:
        return self.update_listing(listing_id, price=f"{price:.2f}")

    def update_inventory(self, listing_id: int, quantity: int) -> Dict[str, Any]:
        return self.update_listing(listing_id, quantity=quantity)

    def get_listings(self, state: str = "active", limit: int = 25, offset: int = 0) -> Dict[str, Any]:
        return self._request(
            "GET",
            f"/shops/{self.shop_id}/listings",
            params={"state": state, "limit": limit, "offset": offset},
        )

    def get_inventory(self, listing_id: int) -> Dict[str, Any]:
        return self._request("GET", f"/listings/{listing_id}/inventory")

    def get_orders(self, limit: int = 25, offset: int = 0) -> Dict[str, Any]:
        return self._request(
            "GET",
            f"/shops/{self.shop_id}/receipts",
            params={"limit": limit, "offset": offset},
        )
