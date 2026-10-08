"""Interactive Etsy setup wizard: python -m app.setup.etsy_wizard"""
from __future__ import annotations

import getpass
import secrets
import sys
import time
from pathlib import Path

if __package__ in (None, ""):  # allow `python app/setup/etsy_wizard.py`
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from app.setup import validators as v

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


def explain_unsaved_credentials() -> None:
    console.print(
        "Credentials were not saved or displayed. Re-enter them in a protected "
        ".env file or configure them as environment variables."
    )


def save_credentials(creds: dict) -> None:
    heading("💾 STEP 7: Save Credentials")
    gi = v.env_is_gitignored(REPO_ROOT)
    if gi is not True:
        console.print(f"  {WARN} .env is not listed in .gitignore — add it before committing!")
    console.print("  [yellow]Never commit .env to Git.[/yellow]")
    if not yes_no("Save to a file? (No keeps credentials hidden)", default=True):
        explain_unsaved_credentials()
        return
    name = ask("File name [.env] (or .env.local):") or ".env"
    if Path(name).name != name or name not in (".env", ".env.local"):
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
            explain_unsaved_credentials()
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
        explain_unsaved_credentials()
        return
    console.print(f"  {OK} Saved to {path}")


def main() -> int:
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
    console.print("\n[bold green]✨ Setup Complete![/bold green] Run a simulation, review it, then publish:")
    console.print("python -m app.sim.run_simulation", highlight=False)
    console.print("python -m app.sim.run_simulation --publish-run run_YYYYMMDD_HHMMSS.json --real", highlight=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
