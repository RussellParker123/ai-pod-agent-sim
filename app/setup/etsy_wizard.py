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
import getpass
import json
import secrets
import sys
import time
import urllib.parse
from pathlib import Path
from typing import List

if __package__ in (None, ""):  # allow `python app/setup/etsy_wizard.py`
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.integrations import etsy_auth, etsy_client
from app.integrations.config import DATA_DIR, SECRETS_DIR, ensure_secrets_dir
from app.setup import validators as v
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

DEFAULT_NICHES = [
    "cozy autumn",
    "pet lovers",
    "minimalist motivation",
    "retro outdoors",
    "bookish humor",
    "coffee culture",
    "western desert",
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
    p.add_argument("--interactive", action="store_true", help="Run the guided credential setup wizard")
    return p


def main(argv: List[str] = None) -> None:
    args = build_arg_parser().parse_args(argv)

    if args.interactive:
        return interactive_main()

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


console = Console()
REPO_ROOT = Path(__file__).resolve().parents[2]
SIGNUP_URL = "https://www.etsy.com/sell"
DEV_URL = "https://www.etsy.com/developers"
AUTH_URL = "https://www.etsy.com/oauth/connect"
REDIRECT_URI = "http://localhost:3003/oauth/redirect"
SCOPES = "listings_r listings_w listings_d shops_r"

OK, BAD, WARN = "[green]✓[/green]", "[red]✗[/red]", "[yellow]![/yellow]"


def ask(prompt: str, secret: bool = False) -> str:
    return (getpass.getpass(prompt + " ") if secret else input(prompt + " ")).strip()


def yes_no(prompt: str, default: bool = False) -> bool:
    ans = input(f"{prompt} ({'Y/n' if default else 'y/N'}): ").strip().lower()
    return default if not ans else ans.startswith("y")


def heading(text: str) -> None:
    console.print(f"\n[bold cyan]{text}[/bold cyan]")


def manual_step(title: str, lines: list) -> None:
    heading(title)
    for line in lines:
        console.print(f"  → {line}", highlight=False)
    input("  Press ENTER when done... ")


def credential_table() -> None:
    table = Table(title="Credentials needed")
    table.add_column("Variable", style="cyan")
    table.add_column("Where to find it")
    table.add_row("ETSY_API_KEY", "Developer Portal → Your Apps → Keystring")
    table.add_row("ETSY_API_SECRET", "Developer Portal → Your Apps → Shared secret")
    table.add_row("ETSY_SHOP_ID", "Numeric shop ID (see ETSY_WIZARD_GUIDE.md)")
    table.add_row("ETSY_ACCESS_TOKEN", "OAuth access token from step 3")
    console.print(table)


def prompt_valid(label: str, check, secret: bool = False) -> str:
    while True:
        value = ask(label + ":", secret=secret)
        ok, msg = check(value)
        if ok:
            return value
        console.print(f"  {BAD} {msg}")


def collect_credentials() -> dict:
    heading("📝 STEP 4: Enter API Credentials")
    credential_table()
    console.print("  [dim]Secret inputs are hidden while typing.[/dim]")
    return {
        "ETSY_API_KEY": prompt_valid("API Key", v.validate_api_key, secret=True),
        "ETSY_API_SECRET": prompt_valid("API Secret", v.validate_api_secret, secret=True),
        "ETSY_SHOP_ID": prompt_valid("Shop ID", v.validate_shop_id),
        "ETSY_ACCESS_TOKEN": prompt_valid("Access Token", v.validate_access_token, secret=True),
    }


def validate_credentials(creds: dict) -> bool:
    heading("✅ STEP 5: Validating...")
    with Progress(SpinnerColumn(), TextColumn("{task.description}"), console=console, transient=True) as prog:
        task = prog.add_task("Testing API connection...", total=None)
        try:
            ok, msg = v.test_shop_access(creds)
        except v.EtsyNetworkError:
            prog.stop()
            console.print(f"  {BAD} Network error. Check your internet connection and try again.")
            return False
        prog.update(task, description="Checking shop access...")
    if ok:
        console.print(f"  {OK} API connection\n  {OK} Shop access\n  [green]All credentials valid![/green]")
    else:
        console.print(f"  {BAD} {msg}")
    return ok


def create_test_listing(creds: dict) -> None:
    heading("🎨 STEP 6: Create Test Listing?")
    if not yes_no("Create a draft test listing on Etsy to verify full integration?"):
        return
    title = f"TEST: AI Art - {time.strftime('%Y-%m-%d %H:%M:%S')}"
    data = {
        "title": title,
        "description": "Test listing created by the AI POD setup wizard. AI-generated artwork.",
        "price": "5.00",
        "quantity": 1,
        "who_made": "i_did",
        "when_made": "made_to_order",
        "taxonomy_id": 1,
        "type": "download",
        "state": "draft",
        "is_supply": "false",
    }
    try:
        resp = v.request("POST", f"/shops/{creds['ETSY_SHOP_ID']}/listings", creds, data=data)
    except v.EtsyNetworkError:
        console.print(f"  {BAD} Network error. Check your internet connection.")
        return
    if resp.status_code not in (200, 201):
        console.print(f"  {BAD} Could not create listing: {v.explain_response(resp)}")
        return
    listing_id = resp.json().get("listing_id")
    console.print(f"  {OK} Created draft listing: {title}")
    console.print(f"  URL: https://www.etsy.com/listing/{listing_id}", highlight=False)
    if yes_no("Delete the test listing now? (No keeps it as a draft)"):
        try:
            d = v.request("DELETE", f"/listings/{listing_id}", creds)
        except v.EtsyNetworkError:
            console.print(f"  {BAD} Network error while deleting; delete it manually on Etsy.")
            return
        if d.status_code in (200, 204):
            console.print(f"  {OK} Test listing deleted")
        else:
            console.print(f"  {BAD} Delete failed: {v.explain_response(d)}")


def print_credentials(creds: dict) -> None:
    console.print("\n[bold]Add these to your .env manually:[/bold]")
    for k, val in creds.items():
        console.print(f"{k}={val}", highlight=False, markup=False)


def save_credentials(creds: dict) -> None:
    heading("💾 STEP 7: Save Credentials")
    gi = v.env_is_gitignored(REPO_ROOT)
    if gi is not True:
        console.print(f"  {WARN} .env is not listed in .gitignore — add it before committing!")
    console.print("  [yellow]Never commit .env to Git.[/yellow]")
    if not yes_no("Save to a file? (No prints credentials for manual setup)", default=True):
        print_credentials(creds)
        return
    name = ask("File name [.env] (or .env.local):") or ".env"
    if Path(name).name != name or not name.startswith(".env"):
        console.print(f"  {BAD} Use .env or .env.local (inside the project folder).")
        name = ".env"
    path = REPO_ROOT / name
    if v.env_is_gitignored(REPO_ROOT, name) is not True:
        console.print(f"  {WARN} {name} is not covered by .gitignore.")
    existing = v.existing_credentials(path)
    if existing:
        shown = ", ".join(f"{k}={v.mask(x)}" for k, x in existing.items())
        console.print(f"  {WARN} {name} already has credentials: {shown}")
        if not yes_no("Overwrite them?"):
            print_credentials(creds)
            return
    try:
        lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
        lines = [ln for ln in lines if ln.split("=", 1)[0].strip() not in creds]
        lines += [f"{k}={val}" for k, val in creds.items()]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        try:
            path.chmod(0o600)
        except OSError:
            pass
    except PermissionError:
        console.print(f"  {BAD} Permission denied writing {path}. Try `chmod u+w` or run as administrator.")
        print_credentials(creds)
        return
    console.print(f"  {OK} Saved to {path}")


def interactive_main() -> int:
    console.print("[bold magenta]Welcome to Etsy Setup Wizard![/bold magenta]")
    console.print("This will help you connect your AI POD simulation to Etsy.")
    try:
        manual_step("📋 STEP 1: Create Etsy Account", [
            f"Visit: {SIGNUP_URL}", 'Click "Start selling"', "Complete signup with your email"])
        manual_step("🔑 STEP 2: Register Developer App", [
            f"Visit: {DEV_URL}", 'Create new app named "AI POD Agent Simulator"',
            "Accept terms, note your API Key & Secret"])
        key = ask("Enter your API key (to build the authorization link, optional):", secret=True)
        state = secrets.token_urlsafe(8)
        link = (f"{AUTH_URL}?response_type=code&client_id={key or '<YOUR_API_KEY>'}"
                f"&redirect_uri={REDIRECT_URI}&scope={SCOPES.replace(' ', '%20')}&state={state}"
                "&code_challenge=<PKCE_CHALLENGE>&code_challenge_method=S256")
        manual_step("🔓 STEP 3: Generate OAuth Token", [
            "Visit the authorization URL (see ETSY_WIZARD_GUIDE.md for PKCE details):",
            link, 'Click "Allow access"',
            "Exchange the code from the redirect URL for an access token"])
        while True:
            creds = collect_credentials()
            if validate_credentials(creds):
                break
            if not yes_no("Re-enter credentials?", default=True):
                console.print("Skipping validation is not supported; exiting.")
                return 1
        create_test_listing(creds)
        save_credentials(creds)
    except (KeyboardInterrupt, EOFError):
        console.print("\n[yellow]Cancelled. Nothing further was saved.[/yellow]")
        return 130
    console.print("\n[bold green]✨ Setup Complete![/bold green] You can now run:")
    console.print("python -m app.sim.run_simulation --real", highlight=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
