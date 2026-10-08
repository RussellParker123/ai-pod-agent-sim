"""Validation helpers for Etsy credentials."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, Optional, Tuple

import requests

API_BASE = "https://openapi.etsy.com/v3/application"
CREDENTIAL_KEYS = ("ETSY_API_KEY", "ETSY_API_SECRET", "ETSY_SHOP_ID", "ETSY_ACCESS_TOKEN")
TIMEOUT = 15


class EtsyNetworkError(Exception):
    """Raised when Etsy cannot be reached."""


def mask(value: str) -> str:
    """Show only the first 4 and last 4 characters of a secret."""
    if not value:
        return ""
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}{'*' * (len(value) - 8)}{value[-4:]}"


def validate_api_key(key: str) -> Tuple[bool, str]:
    key = (key or "").strip()
    if not key:
        return False, "API key is empty."
    if not re.fullmatch(r"[A-Za-z0-9]{16,64}", key):
        return False, "API key looks invalid (expected 16-64 letters/digits, no spaces) - check for typos."
    return True, ""


def validate_api_secret(secret: str) -> Tuple[bool, str]:
    secret = (secret or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9]{6,64}", secret):
        return False, "API secret looks invalid (expected letters/digits, no spaces) - check for typos."
    return True, ""


def validate_shop_id(shop_id: str) -> Tuple[bool, str]:
    shop_id = (shop_id or "").strip()
    if not shop_id.isdigit():
        return False, "Shop ID must be numeric (digits only)."
    if not 1 <= int(shop_id) <= 10**12:
        return False, "Shop ID is outside a reasonable range."
    return True, ""


def validate_access_token(token: str) -> Tuple[bool, str]:
    token = (token or "").strip()
    if len(token) < 20 or re.search(r"\s", token):
        return False, "Access token looks invalid (too short or contains spaces) - check for typos."
    return True, ""


def _headers(creds: Dict[str, str]) -> Dict[str, str]:
    return {
        "x-api-key": creds["ETSY_API_KEY"],
        "Authorization": "Bearer " + creds["ETSY_ACCESS_TOKEN"],
    }


def request(method: str, path: str, creds: Dict[str, str], **kwargs) -> requests.Response:
    try:
        return requests.request(
            method, f"{API_BASE}{path}", headers=_headers(creds), timeout=TIMEOUT, **kwargs
        )
    except requests.RequestException as exc:
        raise EtsyNetworkError(str(exc)) from exc


def explain_response(resp: requests.Response) -> str:
    if resp.status_code == 429:
        return ("Rate limit reached. Etsy limits requests per second and per day per app; "
                "wait a bit and retry.")
    if resp.status_code in (401, 403):
        return "Etsy rejected the credentials. Check the API key and that the access token is valid/unexpired."
    if resp.status_code == 404:
        return "Shop not found. Check the Shop ID."
    return f"Etsy returned HTTP {resp.status_code}."


def test_shop_access(creds: Dict[str, str]) -> Tuple[bool, str]:
    """Call Etsy to verify the token can access the shop. Raises EtsyNetworkError on network failure."""
    resp = request("GET", f"/shops/{creds['ETSY_SHOP_ID']}", creds)
    if resp.status_code == 200:
        return True, ""
    return False, explain_response(resp)


def read_env(path: Path) -> Dict[str, str]:
    values: Dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        values[k.strip()] = v.strip().strip('"').strip("'")
    return values


def existing_credentials(path: Path) -> Dict[str, str]:
    env = read_env(path)
    return {k: env[k] for k in CREDENTIAL_KEYS if env.get(k)}


def env_is_gitignored(repo_root: Path, name: str = ".env") -> Optional[bool]:
    """True/False if .gitignore lists the file; None if there is no .gitignore."""
    gi = repo_root / ".gitignore"
    if not gi.exists():
        return None
    for line in gi.read_text(encoding="utf-8").splitlines():
        line = line.strip().lstrip("/")
        if line in (name, ".env*", "*.env"):
            return True
    return False
