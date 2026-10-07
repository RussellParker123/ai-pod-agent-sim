"""Human review decisions used by the review UI and publishing workflow."""
import json
from pathlib import Path
from typing import Dict


def final_review_status(manager_decision: str, compliance_status: str, override: str) -> str:
    if compliance_status != "pass" or manager_decision == "BLOCK":
        return "BLOCKED"
    if override == "cancel" and manager_decision in ("GREENLIGHT", "HOLD"):
        return "CANCELED_BY_USER"
    if override == "approve" and manager_decision == "GREENLIGHT":
        return "APPROVED"
    if override == "force_approve" and manager_decision == "HOLD":
        return "FORCE_APPROVED"
    return "PENDING_REVIEW"


def load_review_overrides(run_name: str, overrides_path: Path) -> Dict[str, str]:
    if not overrides_path.exists():
        return {}
    all_overrides = json.loads(overrides_path.read_text(encoding="utf-8"))
    run_overrides = all_overrides.get(run_name, {})
    return run_overrides if isinstance(run_overrides, dict) else {}
