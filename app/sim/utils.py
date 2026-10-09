from pathlib import Path
import json
import datetime as dt

from app.paths import DATA_DIR  # same directory the live integrations use

DATA_DIR.mkdir(parents=True, exist_ok=True)


def timestamp() -> str:
    return dt.datetime.utcnow().strftime("%Y%m%d_%H%M%S")


def save_json(obj, filename: str) -> Path:
    path = DATA_DIR / filename
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2)
    return path
