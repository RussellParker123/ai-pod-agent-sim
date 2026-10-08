"""Etsy Open API v3 OAuth 2.0 + PKCE authentication.

Handles the one-time browser consent handshake (authorization URL + local
callback server) and ongoing access-token storage/refresh. Tokens are kept
in .secrets/etsy_tokens.json, which is gitignored and never committed.

Usage (interactive, one-time):
    from app.integrations import etsy_auth
    url, verifier, state = etsy_auth.build_authorization_url()
    # user opens `url` in a browser, approves, Etsy redirects to ETSY_REDIRECT_URI
    # either capture it with `run_callback_server()` or paste the redirect URL/code
    tokens = etsy_auth.exchange_code_for_tokens(code, verifier)

Usage (ongoing):
    access_token = etsy_auth.get_valid_access_token()  # refreshes if expired
"""
from __future__ import annotations

import base64
import hashlib
import json
import secrets
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Optional, Tuple

import requests

from app.integrations.config import (
    ETSY_API_KEY,
    ETSY_REDIRECT_URI,
    ETSY_SHARED_SECRET,
    ETSY_TOKENS_PATH,
    NotConfiguredError,
    ensure_secrets_dir,
)

AUTHORIZE_URL = "https://www.etsy.com/oauth/connect"
TOKEN_URL = "https://openapi.etsy.com/v3/public/oauth/token"

DEFAULT_SCOPES = "shops_r shops_w listings_r listings_w listings_d transactions_r transactions_w"


def _require_credentials() -> None:
    if not ETSY_API_KEY or not ETSY_SHARED_SECRET:
        raise NotConfiguredError(
            "ETSY_API_KEY and ETSY_SHARED_SECRET must be set (copy .env.example to .env "
            "and fill them in) before connecting an Etsy shop."
        )


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _make_pkce_pair() -> Tuple[str, str]:
    verifier = _b64url(secrets.token_bytes(64))
    challenge = _b64url(hashlib.sha256(verifier.encode("ascii")).digest())
    return verifier, challenge


def build_authorization_url(scopes: str = DEFAULT_SCOPES) -> Tuple[str, str, str]:
    """Returns (authorization_url, code_verifier, state). Caller must keep the
    verifier + state to complete the handshake."""
    _require_credentials()
    verifier, challenge = _make_pkce_pair()
    state = _b64url(secrets.token_bytes(16))
    params = {
        "response_type": "code",
        "client_id": ETSY_API_KEY,
        "redirect_uri": ETSY_REDIRECT_URI,
        "scope": scopes,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    url = f"{AUTHORIZE_URL}?{urllib.parse.urlencode(params)}"
    return url, verifier, state


class _CallbackHandler(BaseHTTPRequestHandler):
    result: dict = {}

    def do_GET(self):  # noqa: N802 (http.server API)
        parsed = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(parsed.query)
        _CallbackHandler.result["code"] = qs.get("code", [None])[0]
        _CallbackHandler.result["state"] = qs.get("state", [None])[0]
        _CallbackHandler.result["error"] = qs.get("error", [None])[0]
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(
            b"<html><body><h2>Etsy authorization received.</h2>"
            b"You can close this tab and return to the terminal.</body></html>"
        )

    def log_message(self, fmt, *args):  # silence default request logging
        pass


def run_callback_server(expected_state: str, timeout: int = 180) -> str:
    """Blocks until the OAuth redirect hits ETSY_REDIRECT_URI, then returns the code.

    Only usable when ETSY_REDIRECT_URI points at localhost and this machine can
    reach the browser doing the consent (i.e. a local dev machine, not this
    headless session). Raises TimeoutError if no callback arrives in time.
    """
    parsed = urllib.parse.urlparse(ETSY_REDIRECT_URI)
    host = parsed.hostname or "localhost"
    port = parsed.port or 80
    _CallbackHandler.result = {}
    server = HTTPServer((host, port), _CallbackHandler)
    server.timeout = timeout
    server.handle_request()
    result = _CallbackHandler.result
    if not result:
        raise TimeoutError("No OAuth callback received within the timeout window.")
    if result.get("error"):
        raise RuntimeError(f"Etsy authorization failed: {result['error']}")
    if result.get("state") != expected_state:
        raise RuntimeError("OAuth state mismatch; possible CSRF or stale request.")
    code = result.get("code")
    if not code:
        raise RuntimeError("Etsy callback did not include an authorization code.")
    return code


def exchange_code_for_tokens(code: str, code_verifier: str) -> dict:
    _require_credentials()
    resp = requests.post(
        TOKEN_URL,
        json={
            "grant_type": "authorization_code",
            "client_id": ETSY_API_KEY,
            "redirect_uri": ETSY_REDIRECT_URI,
            "code": code,
            "code_verifier": code_verifier,
        },
        timeout=30,
    )
    resp.raise_for_status()
    tokens = resp.json()
    _save_tokens(tokens)
    return tokens


def _save_tokens(tokens: dict) -> None:
    ensure_secrets_dir()
    tokens = dict(tokens)
    tokens["obtained_at"] = time.time()
    with open(ETSY_TOKENS_PATH, "w", encoding="utf-8") as f:
        json.dump(tokens, f, indent=2)


def _load_tokens() -> Optional[dict]:
    if not ETSY_TOKENS_PATH.exists():
        return None
    with open(ETSY_TOKENS_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def refresh_access_token(refresh_token: str) -> dict:
    _require_credentials()
    resp = requests.post(
        TOKEN_URL,
        json={
            "grant_type": "refresh_token",
            "client_id": ETSY_API_KEY,
            "refresh_token": refresh_token,
        },
        timeout=30,
    )
    resp.raise_for_status()
    tokens = resp.json()
    # Etsy may omit refresh_token on refresh responses; keep the old one if so.
    tokens.setdefault("refresh_token", refresh_token)
    _save_tokens(tokens)
    return tokens


def get_valid_access_token() -> str:
    """Returns a usable access token, refreshing it if expired. Raises
    NotConfiguredError if the shop has never been connected (run the
    etsy_wizard's connect step first)."""
    tokens = _load_tokens()
    if not tokens:
        raise NotConfiguredError(
            "No Etsy OAuth tokens found. Run `python -m app.setup.etsy_wizard --connect-etsy` "
            "to authorize this app against your Etsy shop."
        )
    obtained_at = tokens.get("obtained_at", 0)
    expires_in = tokens.get("expires_in", 3600)
    if time.time() < obtained_at + expires_in - 60:
        return tokens["access_token"]
    refreshed = refresh_access_token(tokens["refresh_token"])
    return refreshed["access_token"]


def is_connected() -> bool:
    return _load_tokens() is not None
