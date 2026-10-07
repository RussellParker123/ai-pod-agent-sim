from dataclasses import dataclass, asdict, field
from typing import List, Dict
import logging
import random
import re


LOGGER = logging.getLogger(__name__)


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
    design_concept: str = ""
    market_research: Dict = field(default_factory=dict)
    product_notes: str = ""


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
                                market_research={
                                    "source": "shop_active_listing_tags",
                                    "tag_frequency": count,
                                },
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


def market_research_agent(designs: List[Design]) -> Dict:
    sources = set()
    signals = []
    for design in designs:
        research = design.market_research
        if research.get("source") == "shop_active_listing_tags":
            source = research["source"]
            frequency = research.get("tag_frequency", 0)
            demand_signal = round(
                frequency / max(
                    (item.market_research.get("tag_frequency", 0) for item in designs),
                    default=0,
                ),
                3,
            ) if frequency else 0.0
        else:
            source = "simulated"
            demand_signal = design.trend_score
            research = {
                "source": source,
                "demand_signal": demand_signal,
                "keyword": design.niche,
            }
            design.market_research = research
        research["demand_signal"] = demand_signal
        research["keyword"] = design.niche
        sources.add(source)
        signals.append(
            {
                "design_id": design.design_id,
                "niche": design.niche,
                **research,
            }
        )
    return {
        "source": next(iter(sources)) if len(sources) == 1 else "mixed",
        "signals": signals,
        "limitations": (
            "Etsy signals reflect this shop's active-listing tag frequency, "
            "not marketplace-wide searches or competitor demand."
            if "shop_active_listing_tags" in sources
            else "Market signals are simulated estimates, not live marketplace data."
        ),
    }


def design_agent(designs: List[Design]) -> None:
    design_angles = (
        "a bold emblem with a small hand-drawn accent",
        "a clean geometric motif with a playful hidden detail",
        "a vintage-inspired badge using original shapes",
        "a calm, minimal illustration with generous negative space",
    )
    for index, design in enumerate(designs):
        related_term = design.market_research.get("keyword", design.niche)
        design.design_concept = (
            f"{design.niche.title()} original artwork: {design_angles[index % len(design_angles)]}; "
            f"audience keyword: {related_term}"
        )


def prompt_agent(designs: List[Design]) -> None:
    for d in designs:
        concept = d.design_concept or f"{d.niche} themed artwork"
        d.prompt = (
            f"{concept}, original vector-style artwork, minimal, high contrast, "
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


def mockup_agent(designs: List[Design], product_types=("mug", "tshirt", "tote")) -> None:
    for d in designs:
        d.product_type = random.choice(product_types)
        base_costs = {"mug": 6.5, "tshirt": 9.0, "tote": 7.0}
        d.unit_cost = base_costs[d.product_type]


def sweater_hoodie_agent(designs: List[Design], share: float = 0.25) -> None:
    """Route the strongest concepts to a sweater or hoodie product line."""
    if not designs:
        return
    if not 0 <= share <= 1:
        raise ValueError("share must be between 0 and 1")
    if share == 0:
        return

    apparel_designs = sorted(
        designs, key=lambda design: design.trend_score, reverse=True
    )[:max(1, round(len(designs) * share))]
    apparel_costs = {"hoodie": 24.0, "sweater": 18.0}
    for index, design in enumerate(apparel_designs):
        product_type = "hoodie" if index % 2 == 0 else "sweater"
        design.product_type = product_type
        design.unit_cost = apparel_costs[product_type]
        garment = "front-chest" if product_type == "hoodie" else "center-chest"
        design.product_notes = (
            f"Optimized for a {product_type}: use a bold {garment} print "
            "with clear shapes that remain legible on fabric."
        )
        design.prompt = f"{design.prompt}, {design.product_notes}"


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
