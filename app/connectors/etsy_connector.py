"""Read-only Etsy API connector for the simulation."""

import json
import logging
import os
from pathlib import Path
import time
from decimal import Decimal
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


API_ROOT = "https://api.etsy.com/v3/application"
TOKEN_URL = "https://api.etsy.com/v3/public/oauth/token"
LOGGER = logging.getLogger(__name__)


class EtsyAPIError(Exception):
    """Raised when Etsy cannot fulfill a connector request."""


def configure_etsy_logging(log_path):
    """Write Etsy request and connector-state messages to a dedicated log."""
    LOGGER.setLevel(logging.INFO)
    LOGGER.propagate = False
    if not any(
        isinstance(handler, logging.FileHandler)
        and Path(handler.baseFilename) == Path(log_path).resolve()
        for handler in LOGGER.handlers
    ):
        handler = logging.FileHandler(log_path, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        LOGGER.addHandler(handler)


def load_dotenv(path=None):
    """Load simple KEY=VALUE entries without overriding existing environment."""
    env_path = Path(path) if path else Path(__file__).resolve().parents[2] / ".env"
    if not env_path.is_file():
        return

    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip().strip("\"'")
        os.environ.setdefault(key.strip(), value)


class EtsyConnector:
    """Authenticated Etsy API client exposing read-only shop data."""

    def __init__(
        self,
        shop_id,
        api_key,
        api_secret,
        access_token=None,
        refresh_token=None,
        timeout=15,
    ):
        self.shop_id = str(shop_id)
        self.api_key = api_key
        self.api_secret = api_secret
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.timeout = timeout
        self._token_expires_at = 0

    @classmethod
    def from_environment(cls):
        load_dotenv()
        shop_id = os.getenv("ETSY_SHOP_ID")
        api_key = os.getenv("ETSY_API_KEY")
        api_secret = os.getenv("ETSY_API_SECRET")
        access_token = os.getenv("ETSY_ACCESS_TOKEN")
        refresh_token = os.getenv("ETSY_REFRESH_TOKEN")
        if not all((shop_id, api_key, api_secret)) or not (
            access_token or refresh_token
        ):
            return None
        return cls(
            shop_id,
            api_key,
            api_secret,
            access_token=access_token,
            refresh_token=refresh_token,
        )

    def _refresh_access_token(self):
        if not self.refresh_token:
            raise EtsyAPIError("Etsy access token is missing or expired")

        body = urlencode(
            {
                "grant_type": "refresh_token",
                "client_id": self.api_key,
                "refresh_token": self.refresh_token,
            }
        ).encode("utf-8")
        request = Request(
            TOKEN_URL,
            data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        LOGGER.info("POST %s (OAuth token refresh)", TOKEN_URL)
        try:
            with urlopen(request, timeout=self.timeout) as response:
                token = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
            status = getattr(exc, "code", "network")
            LOGGER.warning("Etsy OAuth refresh failed (%s)", status)
            raise EtsyAPIError(f"Etsy OAuth refresh failed ({status})") from exc

        self.access_token = token.get("access_token")
        self.refresh_token = token.get("refresh_token", self.refresh_token)
        self._token_expires_at = time.time() + int(token.get("expires_in", 3600)) - 30
        if not self.access_token:
            raise EtsyAPIError("Etsy OAuth response did not include an access token")

    def _get(self, path, query=None, retry_auth=True):
        if not self.access_token or (
            self.refresh_token and time.time() >= self._token_expires_at
        ):
            self._refresh_access_token()

        url = f"{API_ROOT}/{path}"
        if query:
            url = f"{url}?{urlencode(query)}"
        request = Request(
            url,
            headers={
                "x-api-key": f"{self.api_key}:{self.api_secret}",
                "Authorization": "Bearer " + str(self.access_token),
                "Accept": "application/json",
            },
        )
        LOGGER.info("GET %s", url)
        try:
            with urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            LOGGER.warning("Etsy API request failed (%s): %s", exc.code, path)
            if exc.code == 401 and retry_auth and self.refresh_token:
                self._token_expires_at = 0
                self._refresh_access_token()
                return self._get(path, query, retry_auth=False)
            if exc.code == 429:
                raise EtsyAPIError("Etsy API rate limit exceeded") from exc
            raise EtsyAPIError(f"Etsy API request failed ({exc.code})") from exc
        except (URLError, TimeoutError, OSError, ValueError) as exc:
            LOGGER.warning("Etsy API request failed (network): %s", path)
            raise EtsyAPIError(
                "Etsy API request failed due to a network or response error"
            ) from exc

    def _get_listings(self, state):
        listings = []
        offset = 0
        while True:
            response = self._get(
                f"shops/{self.shop_id}/listings/{state}",
                {"limit": 100, "offset": offset},
            )
            page = response.get("results", [])
            listings.extend(page)
            if len(page) < 100:
                return listings
            offset += len(page)

    def get_top_trending_search_terms(self, limit=10):
        """Return frequent listing tags as a proxy for shop search trends.

        Etsy does not expose shop search-query analytics through its public API.
        """
        frequencies = {}
        for listing in self._get_listings("active"):
            for tag in listing.get("tags", []):
                term = str(tag).strip()
                if term:
                    frequencies[term] = frequencies.get(term, 0) + 1
        ranked = sorted(
            frequencies.items(), key=lambda item: (-item[1], item[0].lower())
        )
        return [
            {"term": term, "count": count} for term, count in ranked[:limit]
        ]

    def get_historical_flagged_items(self):
        """Return inactive listings as compliance references.

        Etsy's public API does not expose whether an inactive listing was
        specifically flagged or why it was removed.
        """
        return self._get_listings("inactive")

    def get_inventory(self):
        """Return current active listings with available quantity and pricing."""
        inventory = []
        for listing in self._get_listings("active"):
            price = listing.get("price") or {}
            if isinstance(price, dict):
                amount = price.get("amount")
                divisor = price.get("divisor", 1) or 1
                price = amount / divisor if amount is not None else None
            inventory.append(
                {
                    "listing_id": listing.get("listing_id"),
                    "title": listing.get("title", ""),
                    "tags": listing.get("tags", []),
                    "quantity": listing.get("quantity"),
                    "price": price,
                    "currency_code": (
                        listing.get("price", {}).get("currency_code")
                        if isinstance(listing.get("price"), dict)
                        else None
                    ),
                }
            )
        return inventory

    def get_total_sales_usd(self):
        """Return total USD sales from paid, non-cancelled shop receipts."""
        total = Decimal("0")
        offset = 0
        limit = 100
        while True:
            response = self._get(
                f"shops/{self.shop_id}/receipts",
                {"limit": limit, "offset": offset},
            )
            receipts = response.get("results", [])
            for receipt in receipts:
                if not receipt.get("is_paid") or receipt.get("is_cancelled"):
                    continue
                amount = receipt.get("subtotal") or receipt.get("grandtotal") or {}
                if amount.get("currency_code") != "USD":
                    continue
                divisor = amount.get("divisor") or 1
                total += Decimal(str(amount.get("amount", 0))) / Decimal(str(divisor))
            if len(receipts) < limit:
                return float(total)
            offset += limit
