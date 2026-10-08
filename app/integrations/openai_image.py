"""OpenAI image generation client, used for real AI art in live mode.

Falls back to the simulated placeholder (with a warning) when
OPENAI_API_KEY isn't set yet, since the user plans to add it later.
"""
from __future__ import annotations

import base64
import warnings
from pathlib import Path
from typing import List

import requests

from app.integrations.config import DATA_DIR, OPENAI_API_KEY, NotConfiguredError
from app.sim.agents import Design

IMAGES_URL = "https://api.openai.com/v1/images/generations"
MODEL = "gpt-image-1"


def is_configured() -> bool:
    return bool(OPENAI_API_KEY)


def generate_image(prompt: str, out_path: Path, size: str = "1024x1024") -> Path:
    if not OPENAI_API_KEY:
        raise NotConfiguredError(
            "OPENAI_API_KEY is not set. Add it to your .env to enable real AI art generation."
        )
    resp = requests.post(
        IMAGES_URL,
        headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
        json={"model": MODEL, "prompt": prompt, "size": size, "n": 1},
        timeout=120,
    )
    resp.raise_for_status()
    b64_png = resp.json()["data"][0]["b64_json"]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(base64.b64decode(b64_png))
    return out_path


def image_agent_live(designs: List[Design]) -> None:
    """Live replacement for app.sim.agents.image_agent: generates a real
    image per design via OpenAI when configured, otherwise falls back to
    the simulated stub so the pipeline keeps working without the key."""
    if not is_configured():
        warnings.warn(
            "OPENAI_API_KEY not set — falling back to simulated image URIs. "
            "Add the key to .env to generate real AI art.",
            stacklevel=2,
        )
        for d in designs:
            d.image_uri = f"sim://images/{d.design_id}.png"
        return

    images_dir = DATA_DIR / "images"
    for d in designs:
        out_path = images_dir / f"{d.design_id}.png"
        generate_image(d.prompt, out_path)
        d.image_uri = str(out_path)
