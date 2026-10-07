from dataclasses import dataclass, asdict
from typing import List, Dict
import random


@dataclass
class Design:
    design_id: str
    niche: str
    trend_score: float
    prompt: str = ""
    image_uri: str = ""
    compliance_status: str = "pending"
    compliance_notes: str = ""
    product_type: str = ""
    unit_cost: float = 0.0
    price: float = 0.0
    approved: bool = False


@dataclass
class ListingResult:
    design_id: str
    views: int
    clicks: int
    ctr: float
    conversion_rate: float
    orders: int
    revenue: float
    cogs: float
    profit: float


def trend_agent(niches: List[str], k: int = 12) -> List[Design]:
    picks = []
    for i in range(k):
        niche = random.choice(niches)
        picks.append(
            Design(
                design_id=f"D{i+1:03}",
                niche=niche,
                trend_score=round(random.uniform(0.45, 0.95), 3),
            )
        )
    return picks


def prompt_agent(designs: List[Design]) -> None:
    for d in designs:
        d.prompt = (
            f"Original {d.niche} themed vector-style artwork, minimal, high contrast, "
            f"commercial-friendly, no logos, no characters, no trademark terms"
        )


def image_agent(designs: List[Design]) -> None:
    for d in designs:
        d.image_uri = f"sim://images/{d.design_id}.png"


def compliance_agent(designs: List[Design]) -> None:
    for d in designs:
        # simple probabilistic checks for simulation
        trademark_risk = random.random() < 0.12
        similarity_risk = random.random() < 0.10
        if trademark_risk or similarity_risk:
            d.compliance_status = "flagged"
            notes = []
            if trademark_risk:
                notes.append("possible trademark phrase risk")
            if similarity_risk:
                notes.append("style similarity risk")
            d.compliance_notes = "; ".join(notes)
        else:
            d.compliance_status = "pass"
            d.compliance_notes = "no major issues detected"


def mockup_agent(designs: List[Design], product_types=("mug", "tshirt", "tote")) -> None:
    for d in designs:
        d.product_type = random.choice(product_types)
        base_costs = {"mug": 6.5, "tshirt": 9.0, "tote": 7.0}
        d.unit_cost = base_costs[d.product_type]


def pricing_agent(designs: List[Design], target_margin: float = 0.4) -> None:
    for d in designs:
        # price = cost / (1 - margin)
        d.price = round(d.unit_cost / (1 - target_margin), 2)


def approval_gate(designs: List[Design], auto_approve_safe: bool = True) -> None:
    for d in designs:
        if d.compliance_status == "pass" and auto_approve_safe:
            d.approved = True
        else:
            d.approved = False


def listing_simulator(designs: List[Design]) -> List[ListingResult]:
    results = []
    for d in designs:
        if not d.approved:
            results.append(
                ListingResult(
                    design_id=d.design_id,
                    views=0,
                    clicks=0,
                    ctr=0.0,
                    conversion_rate=0.0,
                    orders=0,
                    revenue=0.0,
                    cogs=0.0,
                    profit=0.0,
                )
            )
            continue

        views = random.randint(200, 3000)
        ctr = random.uniform(0.01, 0.06) * (0.8 + d.trend_score)
        clicks = int(views * ctr)
        conversion = random.uniform(0.01, 0.05) * (0.8 + d.trend_score)
        orders = int(clicks * conversion)
        revenue = round(orders * d.price, 2)
        cogs = round(orders * d.unit_cost, 2)
        profit = round(revenue - cogs, 2)

        results.append(
            ListingResult(
                design_id=d.design_id,
                views=views,
                clicks=clicks,
                ctr=round(clicks / views if views else 0.0, 4),
                conversion_rate=round((orders / clicks) if clicks else 0.0, 4),
                orders=orders,
                revenue=revenue,
                cogs=cogs,
                profit=profit,
            )
        )

    return results


def to_serializable(designs: List[Design], results: List[ListingResult]) -> Dict:
    return {
        "designs": [asdict(d) for d in designs],
        "results": [asdict(r) for r in results],
    }
