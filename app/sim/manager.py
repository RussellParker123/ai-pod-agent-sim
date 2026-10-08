"""Manager (overseer) agent with weighted scoring.

Decides GREENLIGHT / HOLD / BLOCK per design and a batch-level GO / PARTIAL / NO-GO.
The human can still cancel or override in the Review page (see app/pages/2_Review.py).
GREENLIGHT here only means 'approved inside the simulation'. Any real marketplace
connector must still require explicit human approval.
"""
from dataclasses import dataclass, asdict
from typing import Callable, List, Dict, Optional
from collections import Counter

from app.sim.agents import Design
from app.sim.characters import DrCypher

WEIGHTS = {"trend": 0.30, "compliance": 0.30, "margin": 0.20, "fit": 0.10, "diversity": 0.10}

PRODUCT_FIT = {
    "coffee culture": {"mug": 0.95, "tshirt": 0.6, "tote": 0.6},
    "bookish humor": {"mug": 0.9, "tote": 0.9, "tshirt": 0.7},
    "minimalist motivation": {"tshirt": 0.9, "mug": 0.8, "tote": 0.7},
    "retro outdoors": {"tshirt": 0.95, "mug": 0.7, "tote": 0.7},
    "pet lovers": {"mug": 0.85, "tshirt": 0.85, "tote": 0.8},
    "cozy autumn": {"mug": 0.9, "tshirt": 0.7, "tote": 0.7},
}

COACH_TIPS = {
    "trend": "Weak trend: swap to a hotter niche or add a seasonal angle to the prompt.",
    "compliance": "Compliance risk: remove brand-like phrases and regenerate with a new seed.",
    "margin": "Thin margin: raise price or switch to a cheaper product type.",
    "fit": "Poor product fit: move this design to a better product (e.g. mug for coffee/book themes).",
    "diversity": "Niche is crowded: differentiate the style or wait for the next batch.",
}


@dataclass
class Decision:
    stage: str
    design_id: str
    action: str
    reason: str


class ManagerAgent:
    def __init__(
        self,
        min_trend: float = 0.55,
        max_per_niche: int = 4,
        max_flag_rate: float = 0.25,
        min_margin: float = 0.30,
        greenlight_at: float = 0.70,
        hold_at: float = 0.50,
        llm_review: Optional[Callable[[str, Dict], str]] = None,
        manager_id: str = "manager-1",
    ):
        self.manager_id = manager_id
        self.min_trend = min_trend
        self.max_per_niche = max_per_niche
        self.max_flag_rate = max_flag_rate
        self.min_margin = min_margin
        self.greenlight_at = greenlight_at
        self.hold_at = hold_at
        self.llm_review = llm_review
        self.decisions: List[Decision] = []
        self.design_scores: Dict[str, Dict] = {}
        self.batch: Dict = {}
        # Dr. Cypher is this manager's persistent character: visits/mood come from real decisions.
        self.character = DrCypher(manager_id=manager_id)

    def _log(self, stage, design_id, action, reason):
        self.decisions.append(Decision(stage, design_id, action, reason))

    def review_trends(self, designs: List[Design]) -> List[Design]:
        kept, per_niche = [], Counter()
        for d in sorted(designs, key=lambda x: x.trend_score, reverse=True):
            if d.trend_score < self.min_trend:
                self._log("trend", d.design_id, "drop", f"trend {d.trend_score} < {self.min_trend}")
            elif per_niche[d.niche] >= self.max_per_niche:
                self._log("trend", d.design_id, "drop", f"niche '{d.niche}' at cap {self.max_per_niche}")
            else:
                per_niche[d.niche] += 1
                kept.append(d)
                self._log("trend", d.design_id, "keep", "strong trend, niche diversity ok")
        self.character.visit(
            "trend", "Reviewing trend picks", [d.design_id for d in kept],
            keep=len(kept), drop=len(designs) - len(kept),
        )
        return kept

    def review_compliance(
        self,
        designs: List[Design],
        recheck: Callable[[List[Design]], None],
        revise: Optional[Callable[[Design], bool]] = None,
        max_retries: int = 1,
    ) -> None:
        """Flagged designs are only re-checked after ``revise`` actually
        changed them (e.g. the prompt was reworked from the compliance
        notes). Unchanged designs are rejected, never re-rolled, and retries
        are capped at ``max_retries`` rounds."""
        flagged = [d for d in designs if d.compliance_status == "flagged"]
        rate = len(flagged) / len(designs) if designs else 0.0
        if rate > self.max_flag_rate:
            self._log("compliance", "-", "note", f"flag rate {rate:.0%} is high: tighten prompts")
        reworked_ids, rejected_ids = [], []
        pending = flagged
        for _ in range(max(0, max_retries)):
            retry = []
            for d in pending:
                notes = d.compliance_notes
                if revise is not None and revise(d):
                    retry.append(d)
                    reworked_ids.append(d.design_id)
                    self._log("compliance", d.design_id, "rework", f"reworked brief from flag: {notes}")
            if not retry:
                break
            recheck(retry)
            pending = [d for d in retry if d.compliance_status == "flagged"]
            for d in retry:
                if d.compliance_status != "flagged":
                    self._log("compliance", d.design_id, "keep", "passed after rework")
            if not pending:
                break
        for d in flagged:
            if d.compliance_status == "flagged":
                rejected_ids.append(d.design_id)
                reason = (
                    "still flagged after rework" if d.design_id in reworked_ids
                    else "flagged; no changed design to re-check"
                )
                self._log("compliance", d.design_id, "reject", f"{reason}: {d.compliance_notes}")
        if self.llm_review:
            self._log("compliance", "-", "note", f"LLM advice: {self.llm_review('compliance', {'flag_rate': rate})}")
        self.character.visit(
            "compliance", "Reviewing compliance flags", [d.design_id for d in flagged],
            rework=len(set(reworked_ids)), reject=len(rejected_ids),
        )

    def review_pricing(self, designs: List[Design]) -> None:
        repriced = []
        for d in designs:
            margin = (d.price - d.unit_cost) / d.price if d.price else 0
            if margin < self.min_margin:
                d.price = round(d.unit_cost / (1 - self.min_margin), 2)
                self._log("pricing", d.design_id, "reprice", f"margin {margin:.0%} below floor; set ${d.price}")
                repriced.append(d.design_id)
        self.character.visit("pricing", "Checking margins", [d.design_id for d in designs], reprice=len(repriced))

    def score_and_decide(self, designs: List[Design]) -> None:
        niche_counts = Counter(d.niche for d in designs)
        for d in designs:
            margin = (d.price - d.unit_cost) / d.price if d.price else 0
            comps = {
                "trend": d.trend_score,
                "compliance": 1.0 if d.compliance_status == "pass" else 0.0,
                "margin": max(0.0, min(1.0, margin / 0.5)),
                "fit": PRODUCT_FIT.get(d.niche, {}).get(d.product_type, 0.6),
                "diversity": max(0.0, 1 - (niche_counts[d.niche] - 1) / max(1, self.max_per_niche)),
            }
            score = round(sum(WEIGHTS[k] * v for k, v in comps.items()), 3)

            reasons = []
            concept = (d.quality or {}).get("concept") or {}
            if d.compliance_status != "pass":
                decision = "BLOCK"
                reasons.append(f"compliance {d.compliance_status}: {d.compliance_notes}")
            elif concept.get("status") == "blocked":
                decision = "BLOCK"
                reasons.append("concept pre-check blocker: " + "; ".join(concept.get("issues", [])))
            elif score >= self.greenlight_at:
                decision = "GREENLIGHT"
            elif score >= self.hold_at:
                decision = "HOLD"
            else:
                decision = "BLOCK"

            weakest = min(comps, key=lambda k: comps[k])
            coach = COACH_TIPS[weakest] if decision == "HOLD" else ""
            if decision != "GREENLIGHT":
                reasons.append(f"weakest component: {weakest} ({comps[weakest]:.2f})")
            if decision == "BLOCK" and score < self.hold_at:
                reasons.append(f"score {score} below hold threshold {self.hold_at}")
            if coach:
                d.review_history.append({"type": "coaching", "source": "manager", "decision": decision,
                                         "feedback": [coach]})
            d.approved = decision == "GREENLIGHT"
            self.design_scores[d.design_id] = {
                "score": score,
                "components": {k: round(v, 3) for k, v in comps.items()},
                "manager_decision": decision,
                "coach": coach,
                "reasons": reasons,
                "concept_check": concept.get("status", "not_run"),
            }
            self._log("approval", d.design_id, decision.lower(), f"score {score}" + (f" | {coach}" if coach else ""))

        counts = Counter(v["manager_decision"] for v in self.design_scores.values())
        total = max(1, len(designs))
        flagged = sum(1 for d in designs if d.compliance_status != "pass")
        if counts["GREENLIGHT"] >= 5 and flagged / total <= self.max_flag_rate:
            status = "GO"
        elif counts["GREENLIGHT"] > 0:
            status = "PARTIAL"
        else:
            status = "NO-GO"
        self.batch = {"status": status, "counts": dict(counts), "flag_rate": round(flagged / total, 3)}
        self._log("approval", "-", "note", f"Batch launch recommendation: {status}")
        self.character.visit(
            "approval", "Scoring and making the greenlight call", [d.design_id for d in designs],
            greenlight=counts["GREENLIGHT"], hold=counts["HOLD"], block=counts["BLOCK"],
        )
        self.character.react(self.batch)

    def score_for(self, design) -> Dict:
        """Scores for a design, falling back to its parent (style variants and
        recycled candidates inherit the parent's scoring)."""
        design_id = design if isinstance(design, str) else design.design_id
        scoring = self.design_scores.get(design_id)
        if scoring is None and not isinstance(design, str) and getattr(design, "parent_design_id", ""):
            scoring = self.design_scores.get(design.parent_design_id)
        if scoring is None:
            scoring = self.design_scores.get(design_id.rsplit("-v", 1)[0])
        return scoring or {}

    def report(self, designs: List[Design], results) -> Dict:
        return {
            "manager_id": self.manager_id,
            "decision_counts": dict(Counter(x.action for x in self.decisions)),
            "approved": sum(1 for d in designs if d.approved),
            "total_revenue": round(sum(r.revenue for r in results), 2),
            "total_profit": round(sum(r.profit for r in results), 2),
            "batch": self.batch,
            "design_scores": self.design_scores,
            "decisions": [asdict(x) for x in self.decisions],
            "character": self.character.to_dict(),
        }
