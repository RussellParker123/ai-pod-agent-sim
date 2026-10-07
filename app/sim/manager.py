"""Manager (overseer) agent.

Supervises every stage of the pipeline, makes keep/reject/revise decisions,
and logs each decision with a reason. Rule-based by default; `llm_review`
is a hook where you can plug in a real LLM for judgment calls.

NOTE: The manager only *recommends* approval inside the simulation. Any real
listing connector must still require explicit human approval.
"""
from dataclasses import dataclass, asdict
from typing import Callable, List, Dict, Optional
from collections import Counter

from app.sim.agents import Design


@dataclass
class Decision:
    stage: str
    design_id: str
    action: str  # keep | drop | retry | reject | reprice | approve | note
    reason: str


class ManagerAgent:
    def __init__(
        self,
        min_trend: float = 0.55,
        max_per_niche: int = 4,
        max_flag_rate: float = 0.25,
        min_margin: float = 0.30,
        llm_review: Optional[Callable[[str, Dict], str]] = None,
    ):
        self.min_trend = min_trend
        self.max_per_niche = max_per_niche
        self.max_flag_rate = max_flag_rate
        self.min_margin = min_margin
        self.llm_review = llm_review  # hook: (stage, context) -> advice text
        self.decisions: List[Decision] = []

    def _log(self, stage, design_id, action, reason):
        self.decisions.append(Decision(stage, design_id, action, reason))

    # ---- Stage 1: trends ----
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
        return kept

    # ---- Stage 2: compliance (one retry, then reject) ----
    def review_compliance(self, designs: List[Design], recheck: Callable[[List[Design]], None]) -> None:
        flagged = [d for d in designs if d.compliance_status == "flagged"]
        rate = len(flagged) / len(designs) if designs else 0.0
        if rate > self.max_flag_rate:
            self._log("compliance", "-", "note",
                      f"flag rate {rate:.0%} > {self.max_flag_rate:.0%}: prompts should be tightened")
        if flagged:
            for d in flagged:
                self._log("compliance", d.design_id, "retry", f"re-check after flag: {d.compliance_notes}")
            recheck(flagged)
        for d in flagged:
            if d.compliance_status == "flagged":
                self._log("compliance", d.design_id, "reject", "still flagged after retry")
            else:
                self._log("compliance", d.design_id, "keep", "passed on retry")
        if self.llm_review:
            advice = self.llm_review("compliance", {"flag_rate": rate})
            self._log("compliance", "-", "note", f"LLM advice: {advice}")

    # ---- Stage 3: pricing ----
    def review_pricing(self, designs: List[Design]) -> None:
        for d in designs:
            margin = (d.price - d.unit_cost) / d.price if d.price else 0
            if margin < self.min_margin:
                d.price = round(d.unit_cost / (1 - self.min_margin), 2)
                self._log("pricing", d.design_id, "reprice", f"margin {margin:.0%} below floor; set ${d.price}")

    # ---- Stage 4: approval recommendation ----
    def final_approval(self, designs: List[Design]) -> None:
        for d in designs:
            if d.compliance_status == "pass":
                d.approved = True
                self._log("approval", d.design_id, "approve", "passed compliance (human sign-off still required for real listing)")
            else:
                d.approved = False
                self._log("approval", d.design_id, "reject", "failed compliance")

    # ---- Report ----
    def report(self, designs: List[Design], results) -> Dict:
        counts = Counter(x.action for x in self.decisions)
        revenue = sum(r.revenue for r in results)
        profit = sum(r.profit for r in results)
        return {
            "decision_counts": dict(counts),
            "approved": sum(1 for d in designs if d.approved),
            "total_revenue": round(revenue, 2),
            "total_profit": round(profit, 2),
            "decisions": [asdict(x) for x in self.decisions],
        }
