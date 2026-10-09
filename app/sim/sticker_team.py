"""Approval workflow for turning reviewed recycled photos into sticker drafts."""
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict

from app.sim import recycling

TEAM_ID = "sticker-recycler-team"
OVERSEER_ID = "sticker-overseer-1"
CYPHER_ID = "dr-cypher"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _record(store, record_id: str, images_root: Path) -> Dict:
    record = store.get(record_id)
    if store.is_blocked_record(record):
        raise recycling.RecyclingError("Quarantined or unusable images cannot be made into stickers.")
    if (record["status"] != recycling.PENDING_REVIEW or record["source"] != "live"
            or record["asset_kind"] != "generated_image"):
        raise recycling.RecyclingError("Sticker production requires a reviewed, real recycled photo.")
    if (record["compliance"].get("status") != "pass"
            or (record.get("analysis") or {}).get("quarantine")):
        raise recycling.RecyclingError("Only compliance-cleared images can enter sticker production.")
    if recycling.safe_image_path(record["image_uri"], images_root) is None:
        raise recycling.RecyclingError("The original image is missing or outside the images folder.")
    return record


def submit_team_review(store, record_id: str, images_root: Path, reviewer: str = "recycler-team") -> Dict:
    record = _record(store, record_id, images_root)
    workflow = record.get("sticker_workflow") or {}
    if workflow.get("status") in ("awaiting_overseer", "awaiting_cypher", "approved", "staged"):
        return record
    record["sticker_workflow"] = {
        "status": "awaiting_overseer",
        "team": TEAM_ID,
        "reviewer": reviewer,
        "image_reviewed": True,
        "submitted_at": _now(),
        "overseer": None,
        "dr_cypher": None,
    }
    record["history"].append({
        "at": _now(), "action": "sticker_team_reviewed", "by": reviewer,
        "note": "Reviewed the original photo and submitted it for overseer approval.",
    })
    store.save()
    return record


def overseer_review(store, record_id: str, images_root: Path) -> Dict:
    record = _record(store, record_id, images_root)
    workflow = record.get("sticker_workflow") or {}
    if workflow.get("status") in ("awaiting_cypher", "approved", "staged"):
        return record
    if workflow.get("status") != "awaiting_overseer" or not workflow.get("image_reviewed"):
        raise recycling.RecyclingError("The recycler team must review the photo before the overseer.")
    analysis = record.get("analysis") or {}
    reusable = any(s.get("type") in recycling.REUSABLE_TYPES
                   for s in analysis.get("suggestions", []))
    checks = {
        "team_viewed_photo": True,
        "compliance_passed": record["compliance"].get("status") == "pass",
        "recycler_analysis_clear": not analysis.get("quarantine"),
        "recycler_found_reuse_option": reusable,
        "photo_available": recycling.safe_image_path(record["image_uri"], images_root) is not None,
    }
    approved = all(checks.values())
    workflow["overseer"] = {
        "agent_id": OVERSEER_ID,
        "approved": approved,
        "checks": checks,
        "reviewed_at": _now(),
    }
    workflow["status"] = "awaiting_cypher" if approved else "rejected"
    record["sticker_workflow"] = workflow
    record["history"].append({
        "at": _now(), "action": "sticker_overseer_reviewed", "by": OVERSEER_ID,
        "note": "Approved." if approved else "Rejected: one or more production checks failed.",
    })
    store.save()
    return record


def cypher_approve(store, record_id: str, images_root: Path) -> Dict:
    record = _record(store, record_id, images_root)
    workflow = record.get("sticker_workflow") or {}
    if workflow.get("status") in ("approved", "staged"):
        return record
    if workflow.get("status") != "awaiting_cypher" or not (workflow.get("overseer") or {}).get("approved"):
        raise recycling.RecyclingError("Dr. Cypher can only approve a photo approved by the overseer.")
    workflow["dr_cypher"] = {
        "agent_id": CYPHER_ID,
        "approved": True,
        "overseer_id": (workflow.get("overseer") or {}).get("agent_id"),
        "approved_at": _now(),
    }
    workflow["status"] = "approved"
    record["sticker_workflow"] = workflow
    record["history"].append({
        "at": _now(), "action": "sticker_cypher_approved", "by": CYPHER_ID,
        "note": "Approved the overseer's recommendation for a die-cut sticker draft.",
    })
    store.save()
    return record


def validate_sticker_approval(store, record_id: str, images_root: Path) -> Dict:
    record = _record(store, record_id, images_root)
    workflow = record.get("sticker_workflow") or {}
    overseer = workflow.get("overseer") or {}
    cypher = workflow.get("dr_cypher") or {}
    checks = overseer.get("checks") or {}
    if (workflow.get("status") != "approved"
            or workflow.get("team") != TEAM_ID
            or not workflow.get("image_reviewed")
            or overseer.get("agent_id") != OVERSEER_ID
            or not overseer.get("approved")
            or not checks
            or not all(checks.values())
            or cypher.get("agent_id") != CYPHER_ID
            or cypher.get("overseer_id") != OVERSEER_ID
            or not cypher.get("approved")):
        raise recycling.RecyclingError("A complete recycler-team, overseer, and Dr. Cypher approval chain is required.")
    return record
