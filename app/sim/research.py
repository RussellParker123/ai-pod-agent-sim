"""Research agent: finds what sells best and briefs the other departments.

The brief feeds the trend agent (boosts best-selling niches), the prompt agent
(style keywords for new images) and the mockup agent (preferred products).
"""
from collections import Counter
from typing import Dict, List, Optional
import logging
import random
import re

from app.sim.agents import Design

LOGGER = logging.getLogger(__name__)

PRODUCT_WORDS = {
    "mug": "mug",
    "tshirt": "tshirt",
    "t-shirt": "tshirt",
    "shirt": "tshirt",
    "tote": "tote",
}
STYLE_WORDS = {
    "minimalist", "retro", "vintage", "boho", "cozy", "funny", "cute",
    "floral", "geometric", "watercolor", "typography", "line art",
}
STOPWORDS = {"the", "and", "for", "with", "gift", "a", "of", "to", "in", "your"}


def _terms(text: str) -> List[str]:
    return [t for t in re.findall(r"[a-z0-9]+", text.lower()) if t not in STOPWORDS]


def _simulated_sellers(niches: List[str]) -> List[Dict]:
    products = ["mug", "tshirt", "tote"]
    styles = sorted(STYLE_WORDS)
    sellers = []
    for niche in niches:
        sellers.append(
            {
                "title": f"{niche} {random.choice(products)}",
                "tags": [niche, random.choice(styles)],
                "demand": random.randint(50, 500),
            }
        )
    return sellers


def research_agent(
    niches: List[str], etsy_connector=None, limit: int = 10
) -> Dict:
    """Return a research brief: top niches, product types and style keywords."""
    sellers: Optional[List[Dict]] = None
    source = "simulated"
    if etsy_connector:
        try:
            sellers = etsy_connector.get_best_sellers(limit=limit)
            source = "etsy"
        except Exception as exc:
            LOGGER.warning("Etsy best sellers unavailable; simulating: %s", exc)
    if not sellers:
        sellers, source = _simulated_sellers(niches), "simulated"

    niche_scores: Counter = Counter()
    products: Counter = Counter()
    styles: Counter = Counter()
    for item in sellers:
        demand = item.get("demand", 0)
        text = " ".join([str(item.get("title", ""))] + [str(t) for t in item.get("tags", [])])
        lowered = text.lower()
        for niche in niches:
            if set(_terms(niche)) & set(_terms(text)):
                niche_scores[niche] += demand
        for word, product in PRODUCT_WORDS.items():
            if word in lowered:
                products[product] += demand
        for style in STYLE_WORDS:
            if style in lowered:
                styles[style] += demand

    total = sum(niche_scores.values()) or 1
    return {
        "source": source,
        "best_sellers": sellers[:limit],
        "top_niches": {n: round(c / total, 3) for n, c in niche_scores.most_common(5)},
        "top_product_types": [p for p, _ in products.most_common(3)],
        "top_styles": [s for s, _ in styles.most_common(3)],
    }


def apply_research(designs: List[Design], research: Dict) -> None:
    """Share research with trend/prompt departments by updating designs."""
    top_niches = research.get("top_niches", {})
    styles = list(research.get("top_styles", []))
    for d in designs:
        weight = top_niches.get(d.niche)
        if weight:
            d.trend_score = round(min(1.0, d.trend_score + 0.1 + 0.2 * weight), 3)
        d.style_keywords = styles or ["minimal"]
