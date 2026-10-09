"""Shared env/config loading for all real-world integrations.

Loads a local .env file (never committed) and exposes the handful of
secrets/paths the Etsy/OpenAI/Printful clients need.
"""
import os

from dotenv import load_dotenv

from app.paths import DATA_DIR, REPO_ROOT, SECRETS_DIR  # noqa: F401 - shared with app/sim (see app/paths.py)

load_dotenv(REPO_ROOT / ".env")

ETSY_API_KEY = os.environ.get("ETSY_API_KEY", "")
ETSY_SHARED_SECRET = os.environ.get("ETSY_SHARED_SECRET", "")
ETSY_REDIRECT_URI = os.environ.get("ETSY_REDIRECT_URI", "http://localhost:8787/callback")

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")

PRINTFUL_API_KEY = os.environ.get("PRINTFUL_API_KEY", "")

ETSY_TOKENS_PATH = SECRETS_DIR / "etsy_tokens.json"


def ensure_secrets_dir() -> None:
    SECRETS_DIR.mkdir(parents=True, exist_ok=True)


class NotConfiguredError(RuntimeError):
    """Raised when a real integration is used without its required API key(s)."""
