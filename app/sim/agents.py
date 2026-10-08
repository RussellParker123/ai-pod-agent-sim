from dataclasses import dataclass, asdict, field
from typing import List, Dict
import logging
import math
import random
import re


LOGGER = logging.getLogger(__name__)
PRODUCT_COSTS = {"mug": 6.5, "tshirt": 9.0, "tote": 7.0}


@dataclass
class Design:
    design_id: str
    niche: str
    trend_score: float
    prompt: str = ""
    style_keywords: List[str] = field(default_factory=list)
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


def trend_agent(niches: List[str], k: int = 12, etsy_connector=None) -> List[Design]:
    if etsy_connector:
        try:
            trends = etsy_connector.get_top_trending_search_terms(limit=10)
            if trends:
                designs = []
                counts = [
                    int(trend.get("count", 0))
                    for trend in trends
                    if isinstance(trend, dict)
                ]
                max_count = max(counts, default=0)
                for i, trend in enumerate(trends[: min(k, 10)]):
                    if isinstance(trend, dict):
                        niche = str(trend.get("term", "")).strip()
                        count = int(trend.get("count", 0))
                    else:
                        niche, count = str(trend).strip(), 0
                    if niche:
                        score = (
                            0.55 + 0.4 * count / max_count
                            if max_count
                            else 0.95 - 0.4 * i / max(1, len(trends))
                        )
                        designs.append(
                            Design(
                                design_id=f"D{i+1:03}",
                                niche=niche,
                                trend_score=round(score, 3),
                            )
                        )
                if designs:
                    return designs
        except Exception as exc:
            LOGGER.warning("Etsy trends unavailable; using simulated trends: %s", exc)

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
        style = ", ".join(d.style_keywords) if d.style_keywords else "minimal"
        d.prompt = (
            f"Original {d.niche} themed vector-style artwork, {style}, high contrast, "
            f"commercial-friendly, no logos, no characters, no trademark terms"
        )


def image_agent(designs: List[Design]) -> None:
    for d in designs:
        d.image_uri = f"sim://images/{d.design_id}.png"


def compliance_agent(designs: List[Design], etsy_connector=None) -> None:
    historical_items = None
    if etsy_connector:
        try:
            historical_items = etsy_connector.get_historical_flagged_items()
        except Exception as exc:
            LOGGER.warning(
                "Etsy compliance references unavailable; using simulated checks: %s",
                exc,
            )

    for d in designs:
        if historical_items is None:
            # Preserve the mock checks when Etsy is disabled or unavailable.
            trademark_risk = random.random() < 0.12
            similarity_risk = random.random() < 0.10
        else:
            trademark_risk = False
            similarity_risk = False
        matched_item = None
        if historical_items is not None:
            design_terms = set(re.findall(r"[a-z0-9]+", d.niche.lower()))
            for item in historical_items:
                item_terms = set(
                    re.findall(
                        r"[a-z0-9]+",
                        " ".join(
                            [str(item.get("title", ""))]
                            + [str(tag) for tag in item.get("tags", [])]
                        ).lower(),
                    )
                )
                shared = design_terms & item_terms
                if len(shared) >= 2 and len(shared) / max(1, len(design_terms)) >= 0.5:
                    matched_item = item
                    similarity_risk = True
                    break
        if trademark_risk or similarity_risk:
            d.compliance_status = "flagged"
            notes = []
            if trademark_risk:
                notes.append("possible trademark phrase risk")
            if similarity_risk:
                notes.append("style similarity risk")
            if matched_item:
                notes.append(
                    "similarity to historical inactive listing: "
                    + str(matched_item.get("title", "untitled"))
                )
            d.compliance_notes = "; ".join(notes)
        else:
            d.compliance_status = "pass"
            d.compliance_notes = "no major issues detected"


def mockup_agent(
    designs: List[Design],
    product_types=("mug", "tshirt", "tote"),
    preferred_product_types=None,
) -> None:
    if not product_types or any(p not in PRODUCT_COSTS for p in product_types):
        raise ValueError("product_types must contain supported products: mug, tshirt, tote")
    for d in designs:
        pool = [p for p in (preferred_product_types or []) if p in product_types]
        d.product_type = random.choice(pool or product_types)
        d.unit_cost = PRODUCT_COSTS[d.product_type]


def pricing_agent(
    designs: List[Design],
    target_margin: float = 0.4,
    market_prices=None,
) -> None:
    if not 0 <= target_margin < 1:
        raise ValueError("target_margin must be between 0 and 1")

    market_prices = market_prices or {}
    for d in designs:
        # Round up so cent precision cannot push the margin below the target.
        cost_floor = math.ceil(
            (d.unit_cost / (1 - target_margin) - 1e-9) * 100
        ) / 100
        benchmark = market_prices.get(d.product_type)
        if not isinstance(benchmark, (int, float)) or isinstance(benchmark, bool):
            benchmark = 0
        if not math.isfinite(benchmark) or benchmark < 0:
            benchmark = 0
        d.price = round(max(cost_floor, benchmark), 2)


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
