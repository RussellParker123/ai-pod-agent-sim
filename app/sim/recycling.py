"""Recycling Facility: a persistent, auditable queue for rejected art.

Only assets that already exist (a generated image, or a simulated image in
simulation runs) are queued. Concept-only rejections have no image and are
never queued, and nothing here generates, regenerates or pays for images.

The recycler agent cross-references each asset's *metadata* (niche, product,
prompt, rejection reason, compliance) against the internal product-fit table,
research brief, approved designs and the image archive, and proposes
alternate uses with confidence, reasons and reference identifiers. It does
not look at pixels unless an optional ``image_inspector`` is supplied.

Safety rules:
- Compliance-flagged/blocked assets are quarantined and can never be
  requested for reuse.
- A reuse request creates a *new* candidate that must pass the current
  compliance, quality, pricing and manager gates plus explicit human
  approval. Original rejection records are never flipped to approved and
  nothing here publishes anything.
- Every action is idempotent; analysis attempts and reuse depth are capped.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Tuple

from app.live.catalog_map import PRODUCT_UNIT_COSTS
from app.sim.agents import Design
from app.sim.art_quality import best_product_for, risky_terms_in
from app.sim.manager import PRODUCT_FIT

RECYCLING_FILENAME = "recycling_queue.json"
MAX_ANALYSIS_ATTEMPTS = 3
MAX_REUSE_DEPTH = 1  # a recycled candidate that is rejected again is not recycled again
MIN_SUGGESTION_CONFIDENCE = 0.5

PENDING_ANALYSIS = "pending_analysis"
PENDING_REVIEW = "pending_review"
QUARANTINED = "quarantined"
REUSE_REQUESTED = "reuse_requested"
REENTERED = "reentered_pipeline"
ARCHIVED = "archived"
UNUSABLE = "unusable"
STATUSES = (PENDING_ANALYSIS, PENDING_REVIEW, QUARANTINED, REUSE_REQUESTED, REENTERED, ARCHIVED, UNUSABLE)
REUSABLE_TYPES = ("alternate_product", "alternate_niche", "crop_rework")

METADATA_LIMITATIONS = (
    "Metadata-based cross-reference only: suggestions come from niche/product/prompt/"
    "rejection metadata and internal reference tables. The image pixels were not inspected; "
    "a human must look at the image before any reuse."
)
_STOP = {"the", "and", "for", "with", "a", "of", "to", "in", "on", "art", "design", "theme",
         "original", "print", "style", "illustration", "lovers", "culture"}


class RecyclingError(ValueError):
    """Raised for invalid recycling actions."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _tokens(text: str) -> set:
    return {t for t in re.findall(r"[a-z0-9]+", (text or "").lower()) if t not in _STOP and len(t) > 2}


def _sid(*parts) -> str:
    return "S-" + hashlib.sha256("|".join(str(p) for p in parts).encode("utf-8")).hexdigest()[:8]


def asset_key(source: str, source_ref: str, design_id: str, image_uri: str) -> str:
    raw = "|".join([source or "", source_ref or "", design_id or "", image_uri or ""])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def safe_image_path(image_uri: str, images_root: Path) -> Optional[Path]:
    """Return a real local file path only if it lives inside ``images_root``
    (no traversal, no arbitrary file reads); otherwise None."""
    if not image_uri or "://" in image_uri:
        return None
    try:
        root = Path(images_root).resolve()
        path = Path(image_uri)
        path = (path if path.is_absolute() else root / path).resolve()
    except (OSError, ValueError):
        return None
    if path.suffix.lower() not in (".png", ".jpg", ".jpeg", ".webp"):
        return None
    if root not in path.parents or not path.is_file():
        return None
    return path


class RecyclingStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.data = {"version": 1, "records": []}
        if self.path.exists():
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict) and isinstance(loaded.get("records"), list):
                self.data = loaded

    @property
    def records(self) -> List[Dict]:
        return self.data["records"]

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def get(self, record_id: str) -> Dict:
        for record in self.records:
            if record["record_id"] == record_id:
                return record
        raise RecyclingError(f"Unknown recycling record '{record_id}'")

    def find(self, **match) -> List[Dict]:
        return [r for r in self.records if all(r.get(k) == v for k, v in match.items())]

    def counts(self) -> Dict[str, int]:
        out = {s: 0 for s in STATUSES}
        for r in self.records:
            out[r["status"]] = out.get(r["status"], 0) + 1
        return out

    def is_blocked_image(self, image_uri: str) -> bool:
        return any(r["image_uri"] == image_uri and r["status"] in (QUARANTINED, UNUSABLE) for r in self.records)

    # --- intake -----------------------------------------------------------
    def enqueue(
        self,
        design: Dict,
        rejected_by: str,
        reason: str,
        source: str,
        source_ref: str = "",
        stage: str = "",
        provenance: Optional[Dict] = None,
    ) -> Tuple[Optional[Dict], str]:
        """Queue an already-generated asset. Returns (record, outcome) where
        outcome is "created", "duplicate" or "skipped_no_image"."""
        image_uri = str(design.get("image_uri") or "")
        design_id = str(design.get("design_id") or "")
        if not image_uri:
            return None, "skipped_no_image"
        key = asset_key(source, source_ref, design_id, image_uri)
        for record in self.records:
            if record["asset_key"] == key:
                return record, "duplicate"
        lineage = dict(design.get("lineage") or {})
        depth = int(lineage.get("depth", 0))
        record = {
            "record_id": "RC-" + key[:10],
            "asset_key": key,
            "source": source,
            "source_ref": source_ref,
            "source_design_id": design_id,
            "image_uri": image_uri,
            "asset_kind": "simulated_image" if image_uri.startswith("sim://") else "generated_image",
            "original": {
                "niche": design.get("niche"),
                "product_type": design.get("product_type"),
                "prompt": design.get("prompt"),
                "brief": copy.deepcopy(design.get("brief") or {}),
                "price": design.get("price"),
                "trend_score": design.get("trend_score"),
                "quality": copy.deepcopy(design.get("quality") or {}),
            },
            "rejection": {"by": rejected_by, "reason": reason, "stage": stage},
            "compliance": {
                "status": design.get("compliance_status", "pending"),
                "notes": design.get("compliance_notes", ""),
            },
            "provenance": dict(provenance or {}),
            "lineage": lineage,
            "status": PENDING_ANALYSIS,
            "analysis": None,
            "analysis_attempts": 0,
            "reuse": None,
            "history": [{"at": _now(), "action": "enqueued", "by": rejected_by, "note": reason}],
            "created_at": _now(),
        }
        if depth >= MAX_REUSE_DEPTH:
            record["status"] = UNUSABLE
            record["history"].append({"at": _now(), "action": "reuse_cap", "by": "system",
                                      "note": f"already recycled {depth} time(s); not offered for reuse again"})
        self.records.append(record)
        return record, "created"

    # --- recycler agent ---------------------------------------------------
    def analyze(
        self,
        record_id: str,
        context: Dict,
        recycler_id: str = "recycler-1",
        image_inspector: Optional[Callable] = None,
        images_root: Optional[Path] = None,
    ) -> Dict:
        record = self.get(record_id)
        if record["status"] not in (PENDING_ANALYSIS, PENDING_REVIEW, QUARANTINED):
            return record  # decided records are not re-analysed
        if record["analysis_attempts"] >= MAX_ANALYSIS_ATTEMPTS:
            raise RecyclingError(f"{record_id} reached the analysis limit ({MAX_ANALYSIS_ATTEMPTS})")
        analysis = cross_reference(record, context)
        local = safe_image_path(record["image_uri"], images_root) if images_root else None
        if image_inspector is not None and local is not None:
            try:
                analysis["image_inspection"] = image_inspector(str(local), record)
                analysis["image_inspected"] = True
            except Exception as exc:  # optional integration: keep metadata result
                analysis["image_inspection"] = {"status": "unavailable", "error": str(exc)}
        analysis.update(recycler_id=recycler_id, analyzed_at=_now())
        record["analysis"] = analysis
        record["analysis_attempts"] += 1
        record["status"] = QUARANTINED if analysis["quarantine"] else PENDING_REVIEW
        record["history"].append({"at": _now(), "action": "analyzed", "by": recycler_id,
                                  "note": f"{len(analysis['suggestions'])} suggestion(s); status {record['status']}"})
        return record

    # --- human actions ----------------------------------------------------
    def review(self, record_id: str, action: str, suggestion_id: str = "", reviewer: str = "human",
               note: str = "") -> Dict:
        record = self.get(record_id)
        if action in ("archive", "mark_unusable"):
            target = ARCHIVED if action == "archive" else UNUSABLE
            if record["status"] == target:
                return record
            if record["status"] == REENTERED:
                raise RecyclingError("Candidate already re-entered the pipeline; reject it in Review instead")
            record["status"] = target
            record["history"].append({"at": _now(), "action": action, "by": reviewer, "note": note})
            return record
        if action != "request_reuse":
            raise RecyclingError(f"Unknown action '{action}'")
        if record["status"] in (REUSE_REQUESTED, REENTERED):
            if record["reuse"] and record["reuse"]["suggestion_id"] == suggestion_id:
                return record  # idempotent repeat
            raise RecyclingError("A reuse candidate already exists for this asset")
        if record["status"] == QUARANTINED:
            raise RecyclingError("Quarantined assets cannot be reused (compliance/safety block)")
        if record["status"] != PENDING_REVIEW:
            raise RecyclingError(f"Cannot request reuse from status '{record['status']}'")
        if int(record["lineage"].get("depth", 0)) >= MAX_REUSE_DEPTH:
            raise RecyclingError("Reuse limit reached for this asset lineage")
        suggestion = next((s for s in (record["analysis"] or {}).get("suggestions", [])
                           if s["suggestion_id"] == suggestion_id), None)
        if suggestion is None:
            raise RecyclingError(f"Unknown suggestion '{suggestion_id}'")
        if suggestion["type"] not in REUSABLE_TYPES:
            raise RecyclingError(f"Suggestion type '{suggestion['type']}' is not a reuse option")
        record["reuse"] = {
            # Unique per record: several runs can reuse the same simulated design ID (e.g. D005).
            "candidate_design_id": (f"{record['source_design_id']}-R{int(record['lineage'].get('depth', 0)) + 1}"
                                    f"-{record['record_id'][3:7]}"),
            "suggestion_id": suggestion_id,
            "type": suggestion["type"],
            "target_niche": suggestion.get("target_niche") or record["original"]["niche"],
            "target_product": suggestion.get("target_product") or record["original"]["product_type"],
            "requested_by": reviewer,
            "requested_at": _now(),
            "status": "awaiting_gates",
            "gates": {k: "pending" for k in ("compliance", "quality", "pricing", "manager", "human_approval")},
            "note": note,
        }
        record["status"] = REUSE_REQUESTED
        record["history"].append({"at": _now(), "action": "request_reuse", "by": reviewer,
                                  "note": f"{suggestion['type']} via {suggestion_id}. {note}".strip()})
        return record

    def build_candidate(self, record_id: str) -> Design:
        """A *new* design that reuses the existing image. It starts unapproved
        with compliance pending, so every gate runs again."""
        record = self.get(record_id)
        if record["status"] != REUSE_REQUESTED or not record.get("reuse"):
            raise RecyclingError("Only reuse-requested records can become candidates")
        reuse = record["reuse"]
        original = record["original"]
        brief = copy.deepcopy(original.get("brief") or {})
        brief["target_product"] = reuse["target_product"]
        trend = original.get("trend_score")
        return Design(
            design_id=reuse["candidate_design_id"],
            niche=reuse["target_niche"] or original.get("niche") or "unknown",
            trend_score=float(trend) if isinstance(trend, (int, float)) else 0.5,
            prompt=original.get("prompt") or "",
            image_uri=record["image_uri"],
            compliance_status="pending",
            compliance_notes="",
            product_type=reuse["target_product"] or "",
            approved=False,
            brief=brief,
            parent_design_id=record["source_design_id"],
            lineage={
                "recycled_from": record["record_id"],
                "source_design_id": record["source_design_id"],
                "suggestion_id": reuse["suggestion_id"],
                "original_rejection": dict(record["rejection"]),
                "depth": int(record["lineage"].get("depth", 0)) + 1,
            },
        )

    def mark_reentered(self, record_id: str, where: str, gates: Dict[str, str]) -> Dict:
        record = self.get(record_id)
        if record["status"] == REENTERED:
            return record
        if record["status"] != REUSE_REQUESTED:
            raise RecyclingError("Only reuse-requested records can re-enter the pipeline")
        record["status"] = REENTERED
        record["reuse"]["status"] = "gates_run"
        record["reuse"]["where"] = where
        record["reuse"]["gates"].update(gates)
        record["history"].append({"at": _now(), "action": "reentered_pipeline", "by": "system",
                                  "note": f"{where}: " + ", ".join(f"{k}={v}" for k, v in gates.items())})
        return record


def build_context(
    research: Optional[Dict] = None,
    approved_designs: Optional[Iterable[Dict]] = None,
    archive: Optional[Iterable[Dict]] = None,
    product_types: Optional[Iterable[str]] = None,
) -> Dict:
    return {
        "product_fit": PRODUCT_FIT,
        "catalog": dict(PRODUCT_UNIT_COSTS),
        "product_types": list(product_types or PRODUCT_UNIT_COSTS.keys()),
        "research": research or {},
        "approved": [
            {"design_id": d.get("design_id"), "niche": d.get("niche"), "product_type": d.get("product_type")}
            for d in (approved_designs or [])
        ],
        "archive": [
            {"design_id": e.get("design_id"), "niche": e.get("niche"), "product_type": e.get("product_type"),
             "manager_decision": e.get("manager_decision")}
            for e in (archive or [])
        ],
    }


def cross_reference(record: Dict, context: Dict) -> Dict:
    """Pure function: explainable, reference-backed reuse suggestions."""
    original = record.get("original") or {}
    niche = original.get("niche") or ""
    product = original.get("product_type") or ""
    brief = original.get("brief") or {}
    reason = (record.get("rejection") or {}).get("reason", "") or ""
    fit_table = context.get("product_fit", {})
    research = context.get("research", {}) or {}
    top_products = list(research.get("top_product_types", []) or [])
    top_niches = dict(research.get("top_niches", {}) or {})
    approved = context.get("approved", [])
    archive = context.get("archive", [])
    allowed = [p for p in context.get("product_types", []) if p in context.get("catalog", {})]
    suggestions: List[Dict] = []
    checked = {"product_fit_niches": len(fit_table), "research_source": research.get("source", "none"),
               "approved_designs": len(approved), "archive_entries": len(archive)}

    compliance = record.get("compliance") or {}
    risky = risky_terms_in(" ".join([niche, original.get("prompt") or "", brief.get("concept", "")]))
    concept_blocked = ((original.get("quality") or {}).get("concept") or {}).get("status") == "blocked"
    if compliance.get("status") != "pass" or risky or concept_blocked:
        why = []
        if compliance.get("status") != "pass":
            why.append(f"compliance {compliance.get('status')}: {compliance.get('notes') or 'no notes'}")
        if risky:
            why.append("protected names in metadata: " + ", ".join(risky))
        return {
            "method": "metadata_cross_reference",
            "image_inspected": False,
            "quarantine": True,
            "suggestions": [{
                "suggestion_id": _sid(record["record_id"], "quarantine"),
                "type": "quarantine",
                "target_niche": None, "target_product": None,
                "confidence": 1.0,
                "reasons": why + ["Unsafe or compliance-flagged assets are never resurfaced as sellable; "
                                  "manual review only."],
                "references": [f"compliance:{record['source_design_id']}"],
            }],
            "references_checked": checked,
            "limitations": METADATA_LIMITATIONS,
        }

    fits = fit_table.get(niche, {})
    orig_fit = fits.get(product)
    reason_l = reason.lower()
    for p in allowed:
        if p == product or p not in fits:
            continue
        fit = fits[p]
        better = orig_fit is None or fit > orig_fit
        if fit < (0.75 if better else 0.7):
            continue
        refs = [f"product_fit:{niche}:{p}"]
        same = [a for a in approved if a["niche"] == niche and a["product_type"] == p]
        refs += [f"approved_design:{a['design_id']}" for a in same[:3]]
        refs += [f"archive:{a['design_id']}" for a in archive
                 if a["niche"] == niche and a["product_type"] == p and a.get("manager_decision") == "GREENLIGHT"][:2]
        if p in top_products:
            refs.append(f"research:top_product_types:{p}")
        conf = (0.7 if better else 0.55) * fit + (0.1 if same else 0) + (0.1 if p in top_products else 0) + (
            0.1 if ("fit" in reason_l or "margin" in reason_l) else 0)
        reasons = [f"Product-fit table rates '{niche}' on {p} at {fit}"
                   + (f" vs {orig_fit} on the original {product}" if orig_fit is not None else "")]
        if not better:
            reasons.append(f"Lower fit than the original product, but still viable; the rejected listing was "
                           f"the {product} version, so confidence is reduced")
        if same:
            reasons.append(f"{len(same)} approved design(s) already sell this niche on {p}")
        if "margin" in reason_l:
            cost, orig_cost = context["catalog"].get(p), context["catalog"].get(product)
            reasons.append(f"Original rejection mentions margin; unit cost {p} ${cost} vs {product} ${orig_cost}")
        suggestions.append({
            "suggestion_id": _sid(record["record_id"], "product", p),
            "type": "alternate_product", "target_niche": niche, "target_product": p,
            "confidence": round(min(conf, 0.95), 3), "reasons": reasons, "references": refs,
        })

    terms = _tokens(" ".join([niche, brief.get("concept", ""), brief.get("motif", "")]))
    candidates = set(top_niches) | set(fit_table) | {a["niche"] for a in approved if a.get("niche")}
    for cand in sorted(c for c in candidates if c and c != niche):
        overlap = terms & _tokens(cand)
        if not overlap:
            continue
        refs = []
        if cand in top_niches:
            refs.append(f"research:top_niches:{cand}")
        if cand in fit_table:
            refs.append(f"product_fit:{cand}")
        same = [a for a in approved if a["niche"] == cand]
        refs += [f"approved_design:{a['design_id']}" for a in same[:3]]
        target_product = best_product_for(cand, allowed or ["mug", "tshirt", "tote"], research)
        conf = 0.35 + 0.15 * len(overlap) + 0.2 * float(top_niches.get(cand, 0) or 0) + (0.1 if same else 0)
        reasons = [f"Shared motif terms with '{cand}': {', '.join(sorted(overlap))}"]
        if cand in top_niches:
            reasons.append(f"Research ranks '{cand}' as a top niche (weight {top_niches[cand]})")
        if "trend" in reason_l:
            reasons.append("Original rejection cites weak trend; this niche has stronger signals")
        suggestions.append({
            "suggestion_id": _sid(record["record_id"], "niche", cand),
            "type": "alternate_niche", "target_niche": cand, "target_product": target_product,
            "confidence": round(min(conf, 0.9), 3), "reasons": reasons, "references": refs,
        })

    if record.get("asset_kind") == "generated_image" and product in ("tshirt", "tote") and "mug" in allowed:
        suggestions.append({
            "suggestion_id": _sid(record["record_id"], "crop", "mug"),
            "type": "crop_rework", "target_niche": niche, "target_product": "mug",
            "confidence": 0.4,
            "reasons": ["Centered emblem art can often be cropped for a mug side print",
                        "Requires a human to check edges, text and resolution on the actual pixels"],
            "references": [f"image:{record['record_id']}", f"product_fit:{niche}:mug"],
        })

    suggestions.sort(key=lambda s: s["confidence"], reverse=True)
    suggestions = suggestions[:4]
    if not any(s["confidence"] >= MIN_SUGGESTION_CONFIDENCE for s in suggestions):
        suggestions.append({
            "suggestion_id": _sid(record["record_id"], "archive"),
            "type": "archive", "target_niche": None, "target_product": None,
            "confidence": 0.6,
            "reasons": ["No reference-backed alternate use reached the confidence bar; keep on file, do not list."],
            "references": [f"product_fit:{niche}" if niche in fit_table else "product_fit:none"],
        })
    return {
        "method": "metadata_cross_reference",
        "image_inspected": False,
        "quarantine": False,
        "suggestions": suggestions,
        "references_checked": checked,
        "limitations": METADATA_LIMITATIONS,
    }


def recycler_agent(records: List[Dict], store: RecyclingStore, context: Dict, recycler_id: str = "recycler-1",
                   images_root: Optional[Path] = None) -> None:
    """Worker function for the recycling department (used via AgentTeam.run_stage)."""
    for record in records:
        if record["status"] == PENDING_ANALYSIS:
            store.analyze(record["record_id"], context, recycler_id=recycler_id, images_root=images_root)


def enqueue_human_rejections(
    store: RecyclingStore,
    run_name: str,
    designs: Iterable[Dict],
    design_ids: Iterable[str],
    context: Dict,
    reason: str = "canceled by human on the Review page",
    images_root: Optional[Path] = None,
) -> Dict[str, List[str]]:
    """Queue designs a human canceled (simulation runs). Idempotent: saving
    the same overrides twice does not create duplicate records. Designs with
    no generated image are reported as skipped and never generate one."""
    by_id = {str(d.get("design_id")): d for d in designs}
    out: Dict[str, List[str]] = {"created": [], "duplicate": [], "skipped_no_image": [], "unknown": []}
    for design_id in design_ids:
        design = by_id.get(str(design_id))
        if design is None:
            out["unknown"].append(str(design_id))
            continue
        record, outcome = store.enqueue(
            design, rejected_by="human", reason=reason, source="simulation", source_ref=run_name,
            stage="human_review", provenance={"run": run_name, "image_kind": "simulated"
                                              if str(design.get("image_uri", "")).startswith("sim://") else "file"},
        )
        out[outcome].append(record["record_id"] if record else str(design_id))
        if record and outcome == "created" and record["status"] == PENDING_ANALYSIS:
            store.analyze(record["record_id"], context, images_root=images_root)
    return out


OUTCOME_GROUPS = {
    "pending_reuse": (PENDING_ANALYSIS, PENDING_REVIEW, REUSE_REQUESTED, REENTERED),
    "quarantined": (QUARANTINED,),
    "unusable": (ARCHIVED, UNUSABLE),
}


def outcome_counts(records: Iterable[Dict]) -> Dict[str, int]:
    """Counter groups shared by the arena, dashboard and Recycling page."""
    out = {group: 0 for group in OUTCOME_GROUPS}
    for record in records:
        for group, statuses in OUTCOME_GROUPS.items():
            if record.get("status") in statuses:
                out[group] += 1
    return out
