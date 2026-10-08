"""Etsy setup wizard.

1. Collects shop/simulation config: niches, product types, target margin,
   and Etsy's real fee structure (listing/transaction/payment processing).
   Interactive when run in a real terminal; falls back to defaults or CLI
   flags when stdin isn't a TTY (e.g. run by an automation/agent).
2. Optionally drives the one-time Etsy OAuth "connect shop" handshake so
   the live pipeline can call the real Etsy API on the user's behalf.

Examples
--------
Config only, interactive:
    python -m app.setup.etsy_wizard

Config only, non-interactive with overrides:
    python -m app.setup.etsy_wizard --niches "coffee culture,pet lovers" \\
        --margin 0.42 --listing-fee 0.20 --transaction-fee-pct 6.5 \\
        --payment-fee-pct 3 --payment-fee-flat 0.25

Start the Etsy OAuth connect flow (prints an authorization URL):
    python -m app.setup.etsy_wizard --connect-etsy

Finish it once you have the browser redirect URL:
    python -m app.setup.etsy_wizard --complete-etsy-auth --redirect-url "http://localhost:8787/callback?code=...&state=..."
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
from pathlib import Path
from typing import List

from app.integrations import etsy_auth, etsy_client
from app.integrations.config import DATA_DIR, SECRETS_DIR, ensure_secrets_dir

DEFAULT_NICHES = [
    "cozy autumn",
    "pet lovers",
    "minimalist motivation",
    "retro outdoors",
    "bookish humor",
    "coffee culture",
]
DEFAULT_PRODUCT_TYPES = ["mug", "tshirt", "tote"]
DEFAULT_MARGIN = 0.42
# Real Etsy fee structure (see https://www.etsy.com/legal/fees/).
DEFAULT_LISTING_FEE = 0.20
DEFAULT_TRANSACTION_FEE_PCT = 6.5
DEFAULT_PAYMENT_FEE_PCT = 3.0
DEFAULT_PAYMENT_FEE_FLAT = 0.25

CONFIG_PATH = DATA_DIR / "etsy_config.json"
PENDING_AUTH_PATH = SECRETS_DIR / "etsy_oauth_pending.json"


def _prompt(label: str, default):
    if sys.stdin.isatty():
        raw = input(f"{label} [{default}]: ").strip()
        return raw if raw else default
    return default


def collect_config(args: argparse.Namespace) -> dict:
    niches = (
        [n.strip() for n in args.niches.split(",") if n.strip()]
        if args.niches
        else [n.strip() for n in str(_prompt("Niches (comma-separated)", ",".join(DEFAULT_NICHES))).split(",") if n.strip()]
    )
    product_types = (
        [p.strip() for p in args.product_types.split(",") if p.strip()]
        if args.product_types
        else [p.strip() for p in str(_prompt("Product types (comma-separated)", ",".join(DEFAULT_PRODUCT_TYPES))).split(",") if p.strip()]
    )
    margin = args.margin if args.margin is not None else float(_prompt("Target margin (0-1)", DEFAULT_MARGIN))
    listing_fee = args.listing_fee if args.listing_fee is not None else float(_prompt("Etsy listing fee ($)", DEFAULT_LISTING_FEE))
    transaction_fee_pct = (
        args.transaction_fee_pct
        if args.transaction_fee_pct is not None
        else float(_prompt("Etsy transaction fee (%)", DEFAULT_TRANSACTION_FEE_PCT))
    )
    payment_fee_pct = (
        args.payment_fee_pct
        if args.payment_fee_pct is not None
        else float(_prompt("Payment processing fee (%)", DEFAULT_PAYMENT_FEE_PCT))
    )
    payment_fee_flat = (
        args.payment_fee_flat
        if args.payment_fee_flat is not None
        else float(_prompt("Payment processing fee, flat ($)", DEFAULT_PAYMENT_FEE_FLAT))
    )

    return {
        "niches": niches,
        "product_types": product_types,
        "target_margin": margin,
        "fees": {
            "listing_fee": listing_fee,
            "transaction_fee_pct": transaction_fee_pct,
            "payment_fee_pct": payment_fee_pct,
            "payment_fee_flat": payment_fee_flat,
        },
    }


def save_config(config: dict, output: Path) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    with open(output, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)
    return output


def start_etsy_connect() -> None:
    url, verifier, state = etsy_auth.build_authorization_url()
    ensure_secrets_dir()
    with open(PENDING_AUTH_PATH, "w", encoding="utf-8") as f:
        json.dump({"verifier": verifier, "state": state}, f)
    print("Open this URL in a browser and approve access to your Etsy shop:\n")
    print(url)
    print(
        "\nAfter approving, Etsy will redirect your browser to your configured "
        "ETSY_REDIRECT_URI (it may show a 'can't be reached' page if nothing is "
        "listening there locally — that's fine). Copy the FULL resulting URL "
        "from the browser's address bar and complete the connection with:\n"
    )
    print(
        '    python -m app.setup.etsy_wizard --complete-etsy-auth --redirect-url "<paste the full URL here>"'
    )


def complete_etsy_connect(redirect_url: str) -> None:
    if not PENDING_AUTH_PATH.exists():
        raise RuntimeError("No pending Etsy connect request found. Run --connect-etsy first.")
    with open(PENDING_AUTH_PATH, "r", encoding="utf-8") as f:
        pending = json.load(f)

    parsed = urllib.parse.urlparse(redirect_url)
    qs = urllib.parse.parse_qs(parsed.query)
    code = qs.get("code", [None])[0]
    state = qs.get("state", [None])[0]
    if qs.get("error"):
        raise RuntimeError(f"Etsy authorization failed: {qs['error'][0]}")
    if not code:
        raise RuntimeError("Redirect URL did not contain an authorization code.")
    if state != pending["state"]:
        raise RuntimeError("OAuth state mismatch; please restart with --connect-etsy.")

    etsy_auth.exchange_code_for_tokens(code, pending["verifier"])
    PENDING_AUTH_PATH.unlink(missing_ok=True)
    print("Etsy shop connected successfully.")
    me = etsy_client.get_me()
    print(f"Authenticated as Etsy user_id={me.get('user_id')}, shop_id={me.get('shop_id')}")


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--niches", help="Comma-separated niche list")
    p.add_argument("--product-types", help="Comma-separated product types (e.g. mug,tshirt,tote)")
    p.add_argument("--margin", type=float, help="Target profit margin, 0-1")
    p.add_argument("--listing-fee", type=float, help="Etsy per-listing fee in USD")
    p.add_argument("--transaction-fee-pct", type=float, help="Etsy transaction fee, percent")
    p.add_argument("--payment-fee-pct", type=float, help="Payment processing fee, percent")
    p.add_argument("--payment-fee-flat", type=float, help="Payment processing fee, flat USD")
    p.add_argument("--output", type=Path, default=CONFIG_PATH, help="Where to save the config JSON")
    p.add_argument("--connect-etsy", action="store_true", help="Start the Etsy OAuth connect handshake")
    p.add_argument("--complete-etsy-auth", action="store_true", help="Finish a pending Etsy OAuth handshake")
    p.add_argument("--redirect-url", help="Full browser redirect URL (used with --complete-etsy-auth)")
    return p


def main(argv: List[str] = None) -> None:
    args = build_arg_parser().parse_args(argv)

    if args.connect_etsy:
        start_etsy_connect()
        return

    if args.complete_etsy_auth:
        if not args.redirect_url:
            raise SystemExit("--complete-etsy-auth requires --redirect-url")
        complete_etsy_connect(args.redirect_url)
        return

    config = collect_config(args)
    path = save_config(config, args.output)
    print(f"Etsy-mode config saved to {path}")
    print(json.dumps(config, indent=2))


if __name__ == "__main__":
    main()
