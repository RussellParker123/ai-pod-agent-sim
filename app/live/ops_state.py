"""Durable Live Ops console history (data/live_ops_state.json).

The Live Ops page used to keep its console (stage states, event log, Dr.
Cypher's status) and art feed only in local variables, so every Streamlit
rerun or server restart showed an empty console even though real work had
happened. This module records *actual* pipeline events to disk as they
stream, with atomic writes, so the page can show them again later.

Restored data is always presented as recorded history:
- a batch recorded as "running" by a different server process is shown as
  INTERRUPTED (that process is gone; nothing is resumed or replayed);
- stages that were active when it stopped are shown as "interrupted";
- nothing is synthesised — no events, counts or outcomes that weren't
  recorded from a real pipeline event.
"""
from __future__ import annotations

import json
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Tuple

from app.integrations.config import DATA_DIR
from app.live_ops_presentation import MANAGER_NODE, STAGE_NODES
from app.sim import recycling
from app.sim.characters import DrCypher

STATE_FILENAME = "live_ops_state.json"
STATE_PATH = DATA_DIR / STATE_FILENAME
IMAGES_DIR = DATA_DIR / "images"
SCHEMA_VERSION = 1
MAX_EVENTS = 200
MAX_GALLERY = 24
MAX_TEXT = 500

# Identifies this server process. A "running" batch written by any other
# process can't still be running: that process restarted or died.
PROCESS_TOKEN = uuid.uuid4().hex

RUNNING = "running"
COMPLETE = "complete"
FAILED = "failed"
INTERRUPTED = "interrupted"
BATCH_STATUSES = (RUNNING, COMPLETE, FAILED, INTERRUPTED)

_STAGE_KEYS = {key for key, _, _ in STAGE_NODES + [MANAGER_NODE]}
_STAGE_VALUES = ("idle", "active", "done", "error", "interrupted")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _text(value, limit: int = MAX_TEXT) -> str:
    return str(value if value is not None else "")[:limit]


def _atomic_write(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with open(tmp, "x", encoding="utf-8") as f:
            json.dump(obj, f, indent=2)
        tmp.replace(path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def _validate(raw) -> dict:
    """Return a sanitised copy of a saved state, keeping only known fields
    with the expected types. Raises ValueError if the shape is unusable."""
    if not isinstance(raw, dict) or not isinstance(raw.get("version"), int):
        raise ValueError("not a Live Ops state object")
    batch = raw.get("batch")
    if batch is not None:
        if not isinstance(batch, dict) or batch.get("status") not in BATCH_STATUSES:
            raise ValueError("batch lifecycle is missing or has an unknown status")
        batch = {
            "batch_id": _text(batch.get("batch_id"), 64),
            "status": batch["status"],
            "process_token": _text(batch.get("process_token"), 64),
            "started_at": _text(batch.get("started_at"), 40),
            "updated_at": _text(batch.get("updated_at"), 40),
            "finished_at": _text(batch.get("finished_at"), 40) or None,
            "error": _text(batch.get("error")) or None,
            "queued_count": batch.get("queued_count") if isinstance(batch.get("queued_count"), int) else None,
            "params": {k: v for k, v in (batch.get("params") or {}).items()
                       if isinstance(k, str) and isinstance(v, (int, float, bool))},
        }
    events = []
    for ev in raw.get("events") or []:
        if isinstance(ev, dict) and ev.get("stage"):
            events.append({
                "at": _text(ev.get("at"), 40),
                "batch_id": _text(ev.get("batch_id"), 64),
                "stage": _text(ev.get("stage"), 40),
                "status": _text(ev.get("status"), 20),
                "message": _text(ev.get("message")),
                "design_id": _text(ev.get("design_id"), 80) or None,
            })
    stage_state = {k: v for k, v in (raw.get("stage_state") or {}).items()
                   if k in _STAGE_KEYS and v in _STAGE_VALUES}
    cypher = raw.get("cypher") if isinstance(raw.get("cypher"), dict) else {}
    cypher = {k: _text(v, 200) for k, v in cypher.items() if isinstance(k, str) and isinstance(v, (str, int, float))}
    gallery = []
    for item in raw.get("gallery") or []:
        if isinstance(item, dict) and item.get("design_id") and item.get("image_uri"):
            gallery.append({"design_id": _text(item["design_id"], 80), "image_uri": _text(item["image_uri"])})
    return {
        "version": raw["version"],
        "batch": batch,
        "stage_state": stage_state,
        "cypher": cypher,
        "events": events[-MAX_EVENTS:],
        "gallery": gallery[-MAX_GALLERY:],
    }


def load_state(path: Optional[Path] = None) -> Tuple[Optional[dict], Optional[str]]:
    """Returns (state, error). Missing file -> (None, None). Unreadable or
    invalid file -> (None, explanation); the file is never modified here."""
    path = Path(path or STATE_PATH)
    if not path.exists():
        return None, None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return _validate(json.load(f)), None
    except (OSError, ValueError) as e:
        return None, (
            f"Saved Live Ops history at {path} could not be read ({type(e).__name__}: {e}). "
            "It has been left untouched; the next live batch will keep a copy of it as "
            f"{STATE_FILENAME}.corrupt-<timestamp> before recording new history."
        )


def restored_view(state: dict) -> dict:
    """Build what the console should show for previously recorded state.
    Never implies that work from another process is still running."""
    batch = dict(state.get("batch") or {})
    status = batch.get("status")
    if status == RUNNING and batch.get("process_token") != PROCESS_TOKEN:
        status = INTERRUPTED
        batch["interrupted_by"] = "process restart"
    batch["display_status"] = status
    running_here = status == RUNNING

    stage_state = {key: "idle" for key in _STAGE_KEYS}
    stage_state.update(state.get("stage_state") or {})
    if status == INTERRUPTED:
        stage_state = {k: ("interrupted" if v == "active" else v) for k, v in stage_state.items()}

    cypher = DrCypher.from_dict(state.get("cypher") or None).to_dict()
    cypher["status"] = {COMPLETE: "done", FAILED: "error", INTERRUPTED: "interrupted"}.get(status, "active")
    if status == INTERRUPTED:
        cypher["activity"] = "Recorded history · batch interrupted (not running, not resumed)"
        cypher["location"] = cypher["home"]
    elif status == FAILED:
        cypher["activity"] = "Recorded history · batch failed"
    elif status == COMPLETE:
        cypher["activity"] = "Recorded history · batch complete"
        cypher["location"] = cypher["home"]
    elif running_here:
        cypher["activity"] = "Recorded snapshot · batch running in another session of this server"

    log_lines = [
        f"[recorded {ev['at']}] [{ev['stage']}] {ev['message']}" for ev in state.get("events") or []
    ]
    gallery = []
    for item in state.get("gallery") or []:
        path = recycling.safe_image_path(item["image_uri"], IMAGES_DIR)
        gallery.append({"design_id": item["design_id"], "image_uri": str(path) if path else None,
                        "recorded_uri": item["image_uri"]})
    return {
        "batch": batch if state.get("batch") else None,
        "running_here": running_here,
        "stage_state": stage_state,
        "cypher": cypher,
        "log_lines": log_lines,
        "gallery": gallery,
    }


class BatchRecorder:
    """Persists a live batch's real events incrementally while it runs."""

    def __init__(self, params: Optional[dict] = None, path: Optional[Path] = None):
        self.path = Path(path or STATE_PATH)
        previous, error = load_state(self.path)
        if error is not None:
            self._preserve_unreadable()
        self.batch_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:6]
        now = _now()
        self.state = {
            "version": SCHEMA_VERSION,
            "batch": {
                "batch_id": self.batch_id,
                "status": RUNNING,
                "process_token": PROCESS_TOKEN,
                "started_at": now,
                "updated_at": now,
                "finished_at": None,
                "error": None,
                "queued_count": None,
                "params": {k: v for k, v in (params or {}).items() if isinstance(v, (int, float, bool))},
            },
            "stage_state": {},
            "cypher": {},
            # Older batches' events are kept (bounded) as history.
            "events": list((previous or {}).get("events") or [])[-MAX_EVENTS:],
            "gallery": [],
        }
        self.finished = False
        self._write()

    def _preserve_unreadable(self) -> None:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup = self.path.with_name(f"{STATE_FILENAME}.corrupt-{stamp}")
        n = 1
        while backup.exists():
            n += 1
            backup = self.path.with_name(f"{STATE_FILENAME}.corrupt-{stamp}-{n}")
        shutil.copy2(self.path, backup)

    def _write(self) -> None:
        self.state["batch"]["updated_at"] = _now()
        _atomic_write(self.path, self.state)

    def record(self, event: dict, stage_state: dict, cypher: dict, gallery_item: Optional[dict] = None) -> None:
        self.state["events"].append({
            "at": _now(),
            "batch_id": self.batch_id,
            "stage": _text(event.get("stage"), 40),
            "status": _text(event.get("status"), 20),
            "message": _text(event.get("message")),
            "design_id": _text(event.get("design_id"), 80) or None,
        })
        self.state["events"] = self.state["events"][-MAX_EVENTS:]
        self.state["stage_state"] = {k: v for k, v in stage_state.items() if k in _STAGE_KEYS and v in _STAGE_VALUES}
        self.state["cypher"] = {k: _text(v, 200) for k, v in cypher.items() if isinstance(v, (str, int, float))}
        if gallery_item:
            self.state["gallery"] = (self.state["gallery"] + [gallery_item])[-MAX_GALLERY:]
        self._write()

    def finish(self, status: str, error: Optional[str] = None, queued_count: Optional[int] = None,
               stage_state: Optional[dict] = None, cypher: Optional[dict] = None) -> None:
        if self.finished:
            return
        if status not in (COMPLETE, FAILED, INTERRUPTED):
            raise ValueError(f"not a final batch status: {status!r}")
        batch = self.state["batch"]
        batch.update(status=status, finished_at=_now(), error=_text(error) or None, queued_count=queued_count)
        if stage_state is not None:
            self.state["stage_state"] = {k: v for k, v in stage_state.items()
                                         if k in _STAGE_KEYS and v in _STAGE_VALUES}
        if status == INTERRUPTED:
            self.state["stage_state"] = {k: ("interrupted" if v == "active" else v)
                                         for k, v in self.state["stage_state"].items()}
        if cypher is not None:
            self.state["cypher"] = {k: _text(v, 200) for k, v in cypher.items() if isinstance(v, (str, int, float))}
        self.finished = True
        self._write()
