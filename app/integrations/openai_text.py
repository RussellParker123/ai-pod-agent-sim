"""OpenAI chat-completions client: used for real GPT-backed reasoning
agents (trend research, prompt writing) that work alongside the simulated
agents in app/sim/agents.py. Only used in live mode — the simulation
keeps using its own lightweight random/template logic so it stays fast
and free to run.

Falls back gracefully (callers check is_configured()) when
OPENAI_API_KEY isn't set yet.
"""
from __future__ import annotations

import json
import os
from typing import Dict

import requests

from app.integrations.config import NotConfiguredError, OPENAI_API_KEY

CHAT_URL = "https://api.openai.com/v1/chat/completions"
TEXT_MODEL = os.environ.get("OPENAI_TEXT_MODEL", "gpt-4o-mini")


def is_configured() -> bool:
    return bool(OPENAI_API_KEY)


def chat_json(system: str, user: str, model: str = TEXT_MODEL) -> Dict:
    """Calls the chat completions API in JSON mode and returns the parsed
    object. Raises NotConfiguredError if no key, or ValueError if the
    model didn't return valid JSON (callers should fall back gracefully)."""
    if not OPENAI_API_KEY:
        raise NotConfiguredError(
            "OPENAI_API_KEY is not set. Add it to your .env to enable real GPT reasoning agents."
        )
    resp = requests.post(
        CHAT_URL,
        headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
        json={
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.9,
        },
        timeout=60,
    )
    resp.raise_for_status()
    content = resp.json()["choices"][0]["message"]["content"]
    try:
        return json.loads(content)
    except json.JSONDecodeError as e:
        raise ValueError(f"OpenAI chat response wasn't valid JSON: {content!r}") from e
