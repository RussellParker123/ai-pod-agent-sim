"""Single source of truth for where runtime data and credentials live.

Both the simulation (app/sim) and the live integrations (app/integrations,
app/live) resolve their directories here so they always agree.

Defaults keep the historical layout: ``<repo>/data`` and ``<repo>/.secrets``.
To keep runtime files on a persistent volume (e.g. in a container or a cloud
workspace that may be recreated), set these in the environment or ``.env``:

    AI_POD_DATA_DIR=/persistent/ai-pod/data
    AI_POD_SECRETS_DIR=/persistent/ai-pod/secrets

Relative values are resolved against the repository root. Nothing here ever
moves, copies, deletes or overwrites existing files — switching directories
only changes where the app reads and writes from now on.
"""
from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_DIR = REPO_ROOT / "data"
DEFAULT_SECRETS_DIR = REPO_ROOT / ".secrets"

DATA_DIR_ENV = "AI_POD_DATA_DIR"
SECRETS_DIR_ENV = "AI_POD_SECRETS_DIR"

try:  # python-dotenv is a hard dependency, but keep path resolution importable without it
    from dotenv import load_dotenv

    load_dotenv(REPO_ROOT / ".env")
except ImportError:  # pragma: no cover
    pass


def _resolve(env_name: str, default: Path) -> Path:
    raw = (os.environ.get(env_name) or "").strip()
    if not raw:
        return default
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = REPO_ROOT / path
    return path


DATA_DIR = _resolve(DATA_DIR_ENV, DEFAULT_DATA_DIR)
SECRETS_DIR = _resolve(SECRETS_DIR_ENV, DEFAULT_SECRETS_DIR)
