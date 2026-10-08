"""Live pipeline: generates real designs, creates Etsy DRAFT listings and
Printful mockups, and queues everything for human approval.

Nothing in this module ever makes an Etsy listing public or places a real
Printful order — those are the two actions gated behind explicit human
approval (see approve_and_publish() here and order_sync.py for fulfillment).
"""
from __future__ import annotations

import argparse
import json
from dataclasses import replace
from pathlib import Path
from typing import Dict, List

from app.integrations import etsy_client, openai_image, openai_text, printful_client
from app.integrations.config import DATA_DIR
from app.live.catalog_map import PRODUCT_PRINTFUL_VARIANT, PRODUCT_TAXONOMY
from app.live.gpt_agents import prompt_agent_live, trend_agent_live
from app.sim.agents import compliance_agent, mockup_agent, pricing_agent
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


STYLE_MODIFIERS = [
    "bold flat-color vector style",
    "soft painterly watercolor style",
    "retro halftone screen-print style",
    "minimalist single-line-art style",
    "vibrant geometric pop-art style",
]


def _build_image_team(designs: List, team_niches: int, team_size: int) -> List:
    """For the top `team_niches` niches (by trend_score), replaces each of
    their designs with `team_size` style-variant copies — a small "art
    team" each producing a different take on the same trending niche, so
    the manager/human has real options to pick from instead of one shot.
    Every other niche's designs pass through unchanged."""
    if team_niches <= 0 or team_size <= 1 or not designs:
        return designs

    best_by_niche: Dict[str, float] = {}
    for d in designs:
        best_by_niche[d.niche] = max(best_by_niche.get(d.niche, 0.0), d.trend_score)
    popular = {n for n, _ in sorted(best_by_niche.items(), key=lambda kv: kv[1], reverse=True)[:team_niches]}

    expanded = []
    for d in designs:
        if d.niche not in popular:
            expanded.append(d)
            continue
        for i in range(team_size):
            variant = replace(d, design_id=f"{d.design_id}-v{i + 1}")
            style = STYLE_MODIFIERS[i % len(STYLE_MODIFIERS)]
            variant.prompt = f"{d.prompt}, {style}"
            expanded.append(variant)
    return expanded


def run_live_batch(k: int = 6) -> List[dict]:
    """Generates up to k new greenlit designs, creates Etsy draft listings +
    Printful mockups for each, and appends them to the pending-approval queue.
    Returns the newly queued entries. (Drains run_live_batch_stream(); use
    that directly for step-by-step progress, e.g. in a live UI.)"""
    queued: List[dict] = []
    for event in run_live_batch_stream(k):
        if event["stage"] == "complete":
            queued = event["queued"]
    return queued


def run_live_batch_stream(k: int = 6, team_niches: int = 2, team_size: int = 3):
    """Same pipeline as run_live_batch(), but yields a progress event after
    each agent stage completes so a UI can show the real agents working
    live, stage by stage, instead of just a final result. Every stage here
    is the *same* agent function used by the simulation (app/sim/agents.py,
    app/sim/manager.py) — only the image stage swaps in real OpenAI
    generation, and two new stages (etsy, printful) do real API calls that
    don't exist in pure simulation mode.

    team_niches/team_size: the top `team_niches` trending niches each get a
    small "art team" of `team_size` style variants generated in parallel
    (see _build_image_team), instead of a single design. This increases
    real OpenAI spend proportionally — set team_size=1 or team_niches=0 to
    disable and go back to one image per design.

    Yields dicts: {"stage": str, "status": "active"|"done", "message": str,
    "count": Optional[int]}. The final event is
    {"stage": "complete", "queued": [...]}.
    """
    config = load_etsy_config()

    yield {"stage": "etsy_connect", "status": "active", "message": "Connecting to your Etsy shop..."}
    shop = _get_shop_context()
    yield {
        "stage": "etsy_connect",
        "status": "done",
        "message": f"Connected to shop_id={shop['shop_id']}.",
        "count": None,
    }

    manager = ManagerAgent()

    trend_note = "via GPT" if openai_text.is_configured() else "simulated — add OPENAI_API_KEY for real GPT research"
    yield {
        "stage": "trend",
        "status": "active",
        "message": f"Scouting {k * 4} candidate designs across your niches ({trend_note})...",
    }
    designs = trend_agent_live(niches=config["niches"], k=k * 4)
    designs = manager.review_trends(designs)
    yield {
        "stage": "trend",
        "status": "done",
        "message": f"Manager kept {len(designs)} trending design(s).",
        "count": len(designs),
    }

    prompt_note = "via GPT" if openai_text.is_configured() else "templated — add OPENAI_API_KEY for real GPT prompts"
    yield {"stage": "prompt", "status": "active", "message": f"Writing original, trademark-safe prompts ({prompt_note})..."}
    prompt_agent_live(designs)
    yield {"stage": "prompt", "status": "done", "message": f"Wrote {len(designs)} prompt(s).", "count": len(designs)}

    before_team = len(designs)
    designs = _build_image_team(designs, team_niches=team_niches, team_size=team_size)
    added = len(designs) - before_team
    if added > 0:
        yield {
            "stage": "image_team",
            "status": "done",
            "message": f"Assembled art teams of {team_size} on the top {team_niches} trending niche(s) "
            f"(+{added} style variant(s) to generate).",
            "count": len(designs),
        }

    if openai_image.is_configured():
        yield {"stage": "image", "status": "active", "message": f"Generating {len(designs)} real AI image(s) via OpenAI (in parallel)..."}
    else:
        yield {
            "stage": "image",
            "status": "active",
            "message": "OPENAI_API_KEY not set — falling back to simulated image URIs.",
        }
    for finished in openai_image.image_agent_live_stream(designs):
        yield {
            "stage": "image",
            "status": "active",
            "message": f"{finished.design_id} ({finished.niche}) art finished.",
            "design_id": finished.design_id,
            "image_uri": finished.image_uri,
        }
    yield {"stage": "image", "status": "done", "message": f"Generated {len(designs)} image(s).", "count": len(designs)}

    yield {"stage": "compliance", "status": "active", "message": "Checking for trademark/brand similarity risk..."}
    compliance_agent(designs)
    manager.review_compliance(designs, recheck=compliance_agent)
    passed = sum(1 for d in designs if d.compliance_status == "pass")
    yield {
        "stage": "compliance",
        "status": "done",
        "message": f"{passed}/{len(designs)} passed compliance.",
        "count": passed,
    }

    yield {"stage": "mockup", "status": "active", "message": "Assigning product mockups (mug/tshirt/tote)..."}
    mockup_agent(designs, product_types=tuple(config["product_types"]))
    yield {"stage": "mockup", "status": "done", "message": f"Mocked up {len(designs)} product(s).", "count": len(designs)}

    yield {"stage": "pricing", "status": "active", "message": "Pricing for target margin..."}
    pricing_agent(designs, target_margin=config["target_margin"])
    manager.review_pricing(designs)
    yield {"stage": "pricing", "status": "done", "message": f"Priced {len(designs)} design(s).", "count": len(designs)}

    yield {"stage": "manager", "status": "active", "message": "Manager scoring and making the greenlight call..."}
    manager.score_and_decide(designs)
    greenlit = [d for d in designs if d.approved][:k]
    yield {
        "stage": "manager",
        "status": "done",
        "message": f"Greenlit {len(greenlit)}/{len(designs)} design(s) for real listing.",
        "count": len(greenlit),
    }

    yield {
        "stage": "etsy",
        "status": "active",
        "message": f"Creating {len(greenlit)} real Etsy DRAFT listing(s) (not public)...",
    }
    queued = []
    printful_count = 0
    for design in greenlit:
        entry = _stage_design(design, shop)
        queued.append(entry)
        if entry.get("printful_sync_product"):
            printful_count += 1
    yield {
        "stage": "etsy",
        "status": "done",
        "message": f"Created {len(queued)} draft listing(s) on Etsy.",
        "count": len(queued),
    }
    yield {
        "stage": "printful",
        "status": "done",
        "message": f"Created {printful_count} Printful mockup product(s).",
        "count": printful_count,
    }

    pending = _load_pending()
    pending.extend(queued)
    _save_pending(pending)

    yield {"stage": "complete", "queued": queued}


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
    run_p.add_argument("--team-niches", type=int, default=2, help="Top N trending niches that get an art team")
    run_p.add_argument("--team-size", type=int, default=3, help="Style variants generated per art-team niche")

    approve_p = sub.add_parser("approve", help="Publish a pending design's Etsy listing live")
    approve_p.add_argument("design_id")

    reject_p = sub.add_parser("reject", help="Reject a pending design (leaves Etsy listing as draft)")
    reject_p.add_argument("design_id")

    sub.add_parser("list", help="List pending approvals")

    args = p.parse_args()
    if args.action == "run-batch":
        queued = []
        for event in run_live_batch_stream(k=args.k, team_niches=args.team_niches, team_size=args.team_size):
            if event["stage"] == "complete":
                queued = event["queued"]
            else:
                marker = "..." if event["status"] == "active" else "done"
                print(f"[{event['stage']:>12}] {marker:>4} — {event['message']}")
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
