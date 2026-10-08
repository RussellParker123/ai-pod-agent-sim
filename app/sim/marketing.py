"""Draft relevant listing copy and search-visibility actions for human review."""
import re
from typing import List

from app.sim.agents import Design
from app.live.catalog_map import PRODUCT_CATALOG_DETAILS


PRODUCT_NAMES = {"mug": "mug", "tshirt": "t-shirt", "tote": "tote bag"}


def _clean(text: str) -> str:
    return " ".join(re.findall(r"[^\W_]+(?:-[^\W_]+)*", text.lower()))


def marketing_agent(designs: List[Design]) -> None:
    for design in designs:
        design.marketing = {}
        if design.compliance_status != "pass":
            continue
        niche = _clean(design.niche)
        product = PRODUCT_NAMES.get(design.product_type)
        if not niche or not product:
            continue

        primary = f"{niche} {product}"
        styles = list(dict.fromkeys(
            term for style in design.style_keywords if (term := _clean(style))
        ))
        keywords = list(dict.fromkeys(
            [primary, niche] + [f"{style} {product}" for style in styles]
        ))
        candidates = [primary, niche] + [
            f"{word} {product}" for word in niche.split()
        ] + keywords[2:] + [product] + styles
        tags = list(dict.fromkeys(
            term for term in candidates if len(term) <= 20
        ))[:13]
        catalog = PRODUCT_CATALOG_DETAILS.get(design.product_type, {})
        product_name = catalog.get("name", product.title())
        title = f"{product_name} - {niche.title()}"[:140].rstrip()
        description = (
            f"{product_name} featuring {niche}-themed artwork."
            + (f" {catalog['size']}." if catalog else "")
            + (f" Design style: {', '.join(styles)}." if styles else "")
        )
        design.marketing = {
            "source": "design_metadata",
            "primary_keyword": primary,
            "keywords": keywords,
            "title": title,
            "description": description,
            "tags": tags,
            "image_alt_text": f"{niche}-themed artwork on a {product}",
            "recommendations": [
                "Review keyword relevance and trademark safety before publishing; "
                "these are suggestions, not measured search volumes.",
                "Complete accurate marketplace categories and attributes; add "
                "verified materials, dimensions, care, and shipping details.",
                "Use clear product photos and descriptive image alt text where "
                "supported; verify it describes the actual image.",
                "For a website you control: make product pages crawlable, use unique "
                "titles and descriptions, canonical URLs, and an XML sitemap.",
                "For a website you control: add Product structured data with "
                "verified price and availability, and check mobile usability.",
                "Publish helpful niche content linking to relevant products; "
                "avoid keyword stuffing, paid link schemes, and fake reviews.",
                "Record a baseline of impressions, clicks, CTR, and orders using "
                "marketplace analytics or Google Search Console for your own site; "
                "change one listing element at a time and compare equivalent periods.",
            ],
            "limitations": (
                "Draft suggestions only: no live keyword research, indexing, or "
                "ranking guarantees. Marketplace indexing is controlled by the "
                "marketplace. Simulation results are not real SEO performance."
            ),
        }
