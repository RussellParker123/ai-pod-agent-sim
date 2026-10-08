"""Dr. Cypher: the Manager agent as a persistent, inspectable character.

The character's location, activity and mood are derived from the manager's
real decisions in a run (which departments it reviewed, what it kept,
reworked, rejected or greenlit). Dialogue lines are original and are always
plain text; renderers must escape them before inserting into HTML.

Internal spellings (``manager_id``, ``app/utils/dr_cipher.py``) are kept for
compatibility; the visible name is "Dr. Cypher".
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Dict, Iterable, List, Optional

CHARACTER_ID = "dr-cypher"
DISPLAY_NAME = "Dr. Cypher"
AVATAR_KEY = "dr_cipher_svg"  # app/utils/dr_cipher.get_dr_cipher_svg()
HOME_LOCATION = "command"

MOOD_LINES = {
    "elated": "Prototype accepted. Log it, frame it, then make the next one sharper.",
    "satisfied": "Solid work. The data agrees with me, which is how I like it.",
    "skeptical": "Some of this holds up. The rest goes back to the bench with notes.",
    "exasperated": "Nothing ships until the blockers are gone. Back to the drawing tablets.",
    "focused": "Clipboard ready. Show me what the departments produced.",
}

VISIT_LINES = {
    "trend": "Kept {keep}, dropped {drop}. Weak signals do not get my budget.",
    "prompt": "Briefs need a focal motif and a print area. I checked {count}.",
    "compliance": "{rework} reworked, {reject} rejected. Blockers stay blockers.",
    "pricing": "Repriced {reprice}. Margins are not optional.",
    "approval": "Greenlight {greenlight}, hold {hold}, block {block}. Humans have the final say.",
    "recycling": "{count} rejected asset(s) delivered. Find a real use or archive them.",
}


@dataclass
class DrCypher:
    manager_id: str = "manager-1"
    character_id: str = CHARACTER_ID
    display_name: str = DISPLAY_NAME
    title: str = "Manager Agent - Chief Art Scientist"
    avatar: str = AVATAR_KEY
    home: str = HOME_LOCATION
    location: str = HOME_LOCATION
    activity: str = "Reviewing the batch plan"
    mood: str = "focused"
    personality: str = (
        "Exacting and theatrical, but data-driven: praises real fixes, coaches with "
        "concrete notes, and never waives a compliance blocker."
    )
    line: str = MOOD_LINES["focused"]
    visits: List[Dict] = field(default_factory=list)

    def visit(self, department: str, purpose: str, design_ids: Iterable[str] = (), **counts) -> Dict:
        template = VISIT_LINES.get(department, "Inspecting {count} item(s).")
        design_ids = [str(i) for i in design_ids]
        values = {"count": len(design_ids)}
        values.update(counts)
        try:
            line = template.format_map(_Default(values))
        except (KeyError, ValueError):
            line = purpose
        event = {
            "seq": len(self.visits) + 1,
            "department": department,
            "purpose": purpose,
            "design_ids": design_ids[:25],
            "counts": {k: v for k, v in counts.items() if isinstance(v, (int, float))},
            "line": line,
        }
        self.visits.append(event)
        self.location = department
        self.activity = purpose
        self.line = line
        return event

    def react(self, batch: Dict) -> None:
        status = (batch or {}).get("status")
        flag_rate = (batch or {}).get("flag_rate", 0) or 0
        if status == "GO" and flag_rate <= 0.1:
            self.mood = "elated"
        elif status == "GO":
            self.mood = "satisfied"
        elif status == "PARTIAL":
            self.mood = "skeptical"
        elif status == "NO-GO":
            self.mood = "exasperated"
        else:
            self.mood = "focused"
        self.line = MOOD_LINES[self.mood]

    def return_home(self, activity: str = "Writing up the batch report") -> None:
        self.location = self.home
        self.activity = activity

    def to_dict(self) -> Dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Optional[Dict], manager_id: str = "manager-1") -> "DrCypher":
        data = dict(data or {})
        known = {f for f in cls.__dataclass_fields__}
        values = {k: v for k, v in data.items() if k in known}
        values.setdefault("manager_id", manager_id)
        # Identity is stable regardless of what a payload claims.
        values["character_id"] = CHARACTER_ID
        values["display_name"] = DISPLAY_NAME
        values["visits"] = [v for v in values.get("visits", []) if isinstance(v, dict)]
        if values.get("mood") not in MOOD_LINES:
            values["mood"] = "focused"
        return cls(**values)


class _Default(dict):
    def __missing__(self, key):
        return 0


def character_from_report(manager_report: Optional[Dict]) -> DrCypher:
    """Rebuild Dr. Cypher from a run's manager report. Older runs have no
    ``character`` key, so the visits are reconstructed from the recorded
    manager decisions instead."""
    report = manager_report or {}
    if isinstance(report.get("character"), dict):
        return DrCypher.from_dict(report["character"], report.get("manager_id", "manager-1"))
    cypher = DrCypher(manager_id=report.get("manager_id", "manager-1"))
    decisions = [d for d in report.get("decisions", []) if isinstance(d, dict)]
    by_stage: Dict[str, Dict[str, int]] = {}
    for d in decisions:
        by_stage.setdefault(d.get("stage", ""), {}).setdefault(d.get("action", ""), 0)
        by_stage[d.get("stage", "")][d.get("action", "")] += 1
    if "trend" in by_stage:
        cypher.visit("trend", "Reviewed trend picks", keep=by_stage["trend"].get("keep", 0),
                     drop=by_stage["trend"].get("drop", 0))
    if "compliance" in by_stage:
        c = by_stage["compliance"]
        cypher.visit("compliance", "Reviewed compliance flags",
                     rework=c.get("rework", 0) + c.get("retry", 0), reject=c.get("reject", 0))
    if "pricing" in by_stage:
        cypher.visit("pricing", "Checked margins", reprice=by_stage["pricing"].get("reprice", 0))
    if "approval" in by_stage:
        a = by_stage["approval"]
        cypher.visit("approval", "Scored and decided", greenlight=a.get("greenlight", 0),
                     hold=a.get("hold", 0), block=a.get("block", 0))
    cypher.react(report.get("batch", {}))
    cypher.return_home()
    return cypher
