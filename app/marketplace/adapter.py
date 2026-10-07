"""Marketplace adapter interface with simulated and Etsy implementations."""
import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

from app.marketplace.etsy_client import EtsyClient, EtsyError
from app.sim.agents import Design

log = logging.getLogger(__name__)

PRODUCT_TITLES = {
    "mug": "Mug",
    "tshirt": "T-Shirt",
    "tote": "Tote Bag",
    "sweater": "Sweater",
    "hoodie": "Hoodie",
}


class MarketplaceAdapter(ABC):
    name = "abstract"

    @abstractmethod
    def list_design(self, design: Design, real: bool = False) -> Dict[str, Any]:
        """Return listing metadata: listing_id, url, status (plus mode/marketplace)."""


class EtsyAdapter(MarketplaceAdapter):
    name = "etsy"

    def __init__(self, client: Optional[EtsyClient] = None, draft_only: bool = False):
        self.client = client or EtsyClient()
        self.draft_only = draft_only

    def _simulate(self, design: Design, note: str = "") -> Dict[str, Any]:
        return {
            "marketplace": self.name,
            "mode": "simulated",
            "listing_id": f"SIM-{design.design_id}",
            "url": f"sim://etsy/listing/{design.design_id}",
            "status": "draft" if self.draft_only else "active",
            "note": note,
        }

    def list_design(self, design: Design, real: bool = False) -> Dict[str, Any]:
        if not real:
            return self._simulate(design)
        try:
            product = PRODUCT_TITLES.get(design.product_type, design.product_type.title() or "Print")
            title = f"{design.niche.title()} {product} - Original Art"
            description = (
                f"Original {design.niche} design on a {product.lower()}, made to order.\n\n"
                "Design created with AI assistance (AI-generated art disclosure)."
            )
            tags = [design.niche, design.product_type, "ai art", "print on demand"]
            listing = self.client.create_listing(
                title=title,
                description=description,
                price=design.price,
                tags=[t for t in tags if t],
                state="draft" if self.draft_only else "active",
            )
            return {
                "marketplace": self.name,
                "mode": "real",
                "listing_id": listing.get("listing_id"),
                "url": listing.get("url", ""),
                "status": listing.get("state", "draft" if self.draft_only else "active"),
                "note": "",
            }
        except (EtsyError, ValueError, KeyError) as exc:
            log.error("Etsy listing failed for %s: %s; falling back to simulation", design.design_id, exc)
            return self._simulate(design, note=f"fallback: {exc}")


def get_adapter(name: str = "etsy", draft_only: bool = False) -> MarketplaceAdapter:
    if name == "etsy":
        return EtsyAdapter(draft_only=draft_only)
    raise ValueError(f"Unknown marketplace: {name}")
