"""Live pipeline: generates real designs, creates Etsy DRAFT listings and
Printful mockups, and queues everything for human approval.

Nothing in this module ever makes an Etsy listing public or places a real
Printful order — those are the two actions gated behind explicit human
approval (see approve_and_publish() here and order_sync.py for fulfillment).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, List

from app.integrations import etsy_client, openai_image, printful_client
from app.integrations.config import DATA_DIR
from app.live.catalog_map import PRODUCT_PRINTFUL_VARIANT, PRODUCT_TAXONOMY
from app.sim.agents import compliance_agent, mockup_agent, pricing_agent, prompt_agent, trend_agent
from app.sim.manager import ManagerAgent
from app.sim.run_simulation import load_etsy_config

PENDING_APPROVALS_PATH = DATA_DIR / "pending_approvals.json"


def _load_pending() -> List[dict]:
    if PENDING_APPROVALS_PATH.exists():
        with open(PENDING_APPROVALS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def _save_pending(items: List[dict]) -> None:
    PENDING_APPROVALS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(PENDING_APPROVALS_PATH, "w", encoding="utf-8") as f:
        json.dump(items, f, indent=2)


def _get_shop_context() -> Dict:
    me = etsy_client.get_me()
    shop_id = me["shop_id"]
    profiles = etsy_client.get_shipping_profiles(shop_id)
    if not profiles:
        raise RuntimeError(
            "Your Etsy shop has no shipping profiles yet. Create one in the Etsy "
            "seller dashboard before running the live pipeline."
        )
    return {"shop_id": shop_id, "shipping_profile_id": profiles[0]["shipping_profile_id"]}


def run_live_batch(k: int = 6) -> List[dict]:
    """Generates up to k new greenlit designs, creates Etsy draft listings +
    Printful mockups for each, and appends them to the pending-approval queue.
    Returns the newly queued entries."""
    config = load_etsy_config()
    shop = _get_shop_context()

    manager = ManagerAgent()
    designs = trend_agent(niches=config["niches"], k=k * 4)
    designs = manager.review_trends(designs)
    prompt_agent(designs)
    openai_image.image_agent_live(designs)
    compliance_agent(designs)
    manager.review_compliance(designs, recheck=compliance_agent)
    mockup_agent(designs, product_types=tuple(config["product_types"]))
    pricing_agent(designs, target_margin=config["target_margin"])
    manager.review_pricing(designs)
    manager.score_and_decide(designs)

    greenlit = [d for d in designs if d.approved][:k]
    queued = [_stage_design(design, shop) for design in greenlit]

    pending = _load_pending()
    pending.extend(queued)
    _save_pending(pending)
    return queued


def _stage_design(design, shop: Dict) -> dict:
    taxonomy_id = PRODUCT_TAXONOMY.get(design.product_type)
    if taxonomy_id is None:
        raise RuntimeError(f"No Etsy taxonomy mapping for product_type={design.product_type!r}")

    listing = etsy_client.create_draft_listing(
        shop["shop_id"],
        {
            "quantity": 100,
            "title": f"{design.niche.title()} Design — {design.product_type.title()}"[:140],
            "description": design.prompt,
            "price": design.price,
            "who_made": "i_did",
            "when_made": "made_to_order",
            "taxonomy_id": taxonomy_id,
            "shipping_profile_id": shop["shipping_profile_id"],
            "is_supply": False,
        },
    )
    listing_id = listing["listing_id"]

    etsy_image_url = None
    if design.image_uri and Path(design.image_uri).exists():
        image_resp = etsy_client.upload_listing_image(shop["shop_id"], listing_id, design.image_uri)
        etsy_image_url = image_resp.get("url_fullxfull") or image_resp.get("url_570xN")

    printful_product = None
    if printful_client.is_configured() and etsy_image_url:
        variant_id = PRODUCT_PRINTFUL_VARIANT.get(design.product_type)
        if variant_id:
            printful_product = printful_client.create_sync_product(
                name=f"{design.design_id}-{design.product_type}",
                variant_id=variant_id,
                image_url=etsy_image_url,
                retail_price=f"{design.price:.2f}",
            )

    return {
        "design_id": design.design_id,
        "niche": design.niche,
        "product_type": design.product_type,
        "price": design.price,
        "prompt": design.prompt,
        "image_uri": design.image_uri,
        "etsy_listing_id": listing_id,
        "etsy_shop_id": shop["shop_id"],
        "etsy_image_url": etsy_image_url,
        "printful_sync_product": printful_product,
        "status": "pending_approval",
    }


def approve_and_publish(design_id: str) -> dict:
    """Human approval action: publishes the Etsy draft listing live."""
    pending = _load_pending()
    for entry in pending:
        if entry["design_id"] == design_id and entry["status"] == "pending_approval":
            etsy_client.publish_listing(entry["etsy_shop_id"], entry["etsy_listing_id"])
            entry["status"] = "live"
            _save_pending(pending)
            return entry
    raise ValueError(f"No pending approval found for design_id={design_id!r}")


def reject(design_id: str) -> dict:
    pending = _load_pending()
    for entry in pending:
        if entry["design_id"] == design_id and entry["status"] == "pending_approval":
            entry["status"] = "rejected"
            _save_pending(pending)
            return entry
    raise ValueError(f"No pending approval found for design_id={design_id!r}")


def list_pending() -> List[dict]:
    return [e for e in _load_pending() if e["status"] == "pending_approval"]


def list_all() -> List[dict]:
    return _load_pending()


def main() -> None:
    p = argparse.ArgumentParser(description="Live pipeline: real design -> Etsy draft + Printful mockup.")
    sub = p.add_subparsers(dest="action", required=True)

    run_p = sub.add_parser("run-batch", help="Generate a new batch and queue it for approval")
    run_p.add_argument("--k", type=int, default=6)

    approve_p = sub.add_parser("approve", help="Publish a pending design's Etsy listing live")
    approve_p.add_argument("design_id")

    reject_p = sub.add_parser("reject", help="Reject a pending design (leaves Etsy listing as draft)")
    reject_p.add_argument("design_id")

    sub.add_parser("list", help="List pending approvals")

    args = p.parse_args()
    if args.action == "run-batch":
        queued = run_live_batch(k=args.k)
        print(f"Queued {len(queued)} design(s) for approval.")
    elif args.action == "approve":
        entry = approve_and_publish(args.design_id)
        print(f"Published: {entry}")
    elif args.action == "reject":
        entry = reject(args.design_id)
        print(f"Rejected: {entry}")
    elif args.action == "list":
        for entry in list_pending():
            print(entry)


if __name__ == "__main__":
    main()
