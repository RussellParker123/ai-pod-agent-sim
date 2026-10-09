"""Live pipeline: generates real designs, creates Etsy DRAFT listings and
Printful mockups, and queues everything for approval.

By default nothing in this module makes an Etsy listing public or places a
real Printful order — those actions are gated behind explicit human approval
(see approve_and_publish() here and order_sync.py for fulfillment). Opt in to
`manager_auto_publish=True` on run_live_batch_stream() to let the Manager
agent (Dr. Cypher) publish its own highest-confidence designs live; anything
below its confidence threshold still falls back to you for manual approval.
"""
from __future__ import annotations

import argparse
import copy
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

import requests

from app.integrations import etsy_client, openai_image, openai_text, printful_client
from app.integrations.config import DATA_DIR
from app.live.catalog_map import (
    PRODUCT_CATALOG_DETAILS,
    PRODUCT_PRINTFUL_PRODUCT,
    PRODUCT_PRINTFUL_VARIANT,
    PRODUCT_SHIP_DIMENSIONS,
    PRODUCT_TAXONOMY,
    PRODUCT_UNIT_COSTS,
    sticker_configuration_errors,
)
from app.live.gpt_agents import prompt_agent_live, trend_agent_live
from app.sim import recycling
from app.sim import sticker_team
from app.sim.agents import Design, compliance_agent, mockup_agent, pricing_agent
from app.sim.art_quality import assess_concept, assess_generated_image, refine_designs, revise_for_compliance
from app.sim.manager import ManagerAgent
from app.sim.run_simulation import load_etsy_config

PENDING_APPROVALS_PATH = DATA_DIR / "pending_approvals.json"
IMAGE_MANIFEST_PATH = DATA_DIR / "image_manifest.json"
RECYCLING_PATH = DATA_DIR / recycling.RECYCLING_FILENAME
IMAGES_DIR = DATA_DIR / "images"


def _recycling_store() -> recycling.RecyclingStore:
    return recycling.RecyclingStore(RECYCLING_PATH)


def _live_recycling_context() -> dict:
    approved = [e for e in _load_pending() if e.get("status") == "live"]
    return recycling.build_context(approved_designs=approved, archive=list_image_archive())


def _load_pending() -> List[dict]:
    if PENDING_APPROVALS_PATH.exists():
        with open(PENDING_APPROVALS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def _save_pending(items: List[dict]) -> None:
    PENDING_APPROVALS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(PENDING_APPROVALS_PATH, "w", encoding="utf-8") as f:
        json.dump(items, f, indent=2)


def _append_image_manifest(design, manager: ManagerAgent) -> None:
    """Records every real image the moment it's generated — niche, prompt,
    and the Manager's score/decision that justified spending on it — so
    spend is always auditable later, even if the batch crashes before
    reaching Etsy/Printful or a draft never gets approved. See
    list_image_archive() to read this back."""
    manifest = []
    if IMAGE_MANIFEST_PATH.exists():
        with open(IMAGE_MANIFEST_PATH, "r", encoding="utf-8") as f:
            manifest = json.load(f)
    # Art-team style variants (e.g. "D010-v2") are built *after* scoring and
    # share their parent design's score/decision (ManagerAgent.score_for).
    scoring = manager.score_for(design)
    manifest.append(
        {
            "design_id": design.design_id,
            "parent_design_id": design.parent_design_id or None,
            "niche": design.niche,
            "product_type": design.product_type,
            "price": design.price,
            "prompt": design.prompt,
            "image_uri": design.image_uri,
            "manager_score": scoring.get("score"),
            "manager_decision": scoring.get("manager_decision"),
            "compliance_status": design.compliance_status,
            "concept_check": (design.quality.get("concept") or {}).get("status"),
            "image_assessment": (design.quality.get("image") or {}).get("status"),
            "generated_at": datetime.now().isoformat(timespec="seconds"),
        }
    )
    IMAGE_MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(IMAGE_MANIFEST_PATH, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)


def list_image_archive() -> List[dict]:
    """Every real image ever generated, manifested (design_id, niche,
    manager score/decision) when generated after this feature shipped, plus
    any older orphaned files in data/images/ with no manifest record (from
    before image generation moved to the Manager-approval step)."""
    manifest = []
    if IMAGE_MANIFEST_PATH.exists():
        with open(IMAGE_MANIFEST_PATH, "r", encoding="utf-8") as f:
            manifest = json.load(f)
    known_paths = {Path(e["image_uri"]).name for e in manifest if e.get("image_uri")}

    images_dir = DATA_DIR / "images"
    orphaned = []
    if images_dir.exists():
        for path in sorted(images_dir.glob("*.png")):
            if path.name not in known_paths:
                orphaned.append(
                    {
                        "design_id": path.stem,
                        "niche": None,
                        "product_type": None,
                        "price": None,
                        "prompt": None,
                        "image_uri": str(path),
                        "manager_score": None,
                        "manager_decision": None,
                        "generated_at": None,
                    }
                )
    return manifest + orphaned


def stage_archived_image(
    design_id: str,
    image_uri: str,
    niche: str,
    product_type: str,
    price: float,
    description: str,
) -> dict:
    """Turns an already-generated image from the Image Archive — one that
    never got queued (e.g. from a past run that was dropped or crashed
    before completing) — into a real Etsy draft listing + Printful mockup,
    *without* generating any new image or spending any new OpenAI credits.
    The (simulated) compliance check still runs on the metadata you enter,
    and images the Recycling Facility quarantined or marked unusable are
    refused. Appends to the same pending-approval queue as a normal batch
    run — you still click Approve & publish to make it live."""
    design_id = design_id.strip()
    if any(e["design_id"] == design_id for e in _load_pending()):
        raise ValueError(f"design_id={design_id!r} has already been staged once.")
    if _recycling_store().is_blocked_image(image_uri):
        raise ValueError("This image is quarantined/unusable in the Recycling Facility and cannot be staged.")

    design = Design(
        design_id=design_id,
        niche=niche,
        trend_score=0.0,
        prompt=description,
        image_uri=image_uri,
        product_type=product_type,
        unit_cost=PRODUCT_UNIT_COSTS.get(product_type, 7.0),
        price=price,
    )
    compliance_agent([design])
    if design.compliance_status != "pass":
        raise ValueError(f"Compliance check flagged this listing: {design.compliance_notes}")
    design.compliance_notes += " (human selected this archived image for staging)"
    shop = _get_shop_context()
    entry = _stage_design(design, shop)
    entry["published_by"] = None
    entry["source"] = "image_archive"

    pending = _load_pending()
    pending.append(entry)
    _save_pending(pending)
    return entry


def _get_shop_context() -> Dict:
    me = etsy_client.get_me()
    shop_id = me["shop_id"]
    # Picks (or creates) a shipping profile that actually has a usable US
    # domestic destination — a "calculated" profile without a carrier set
    # looks valid but makes Etsy reject every new draft listing with
    # shipping_profile_no_domestic_option on item_weight/item_length.
    shipping_profile_id = etsy_client.get_or_create_domestic_shipping_profile_id(shop_id)
    # Etsy's processing-profiles system (rolled out 2026) requires every
    # physical listing to carry a readiness_state_id alongside
    # shipping_profile_id. Every item here is print-on-demand, so
    # "made_to_order" is always the right state; reuse one if the shop
    # already has it (e.g. set up manually), otherwise create it once.
    readiness_state_id = etsy_client.get_or_create_readiness_state_id(shop_id, "made_to_order")
    # return_policy_id isn't required to save a draft, but Etsy rejects
    # *publishing* (state -> active) any physical listing without one, so
    # it has to be resolved up front alongside everything else a listing
    # needs to go live.
    return_policy_id = etsy_client.get_or_create_return_policy_id(shop_id)
    return {
        "shop_id": shop_id,
        "shipping_profile_id": shipping_profile_id,
        "readiness_state_id": readiness_state_id,
        "return_policy_id": return_policy_id,
    }


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
            # Deep copy so variants never share mutable brief/quality/history/marketing state.
            variant = copy.deepcopy(d)
            variant.design_id = f"{d.design_id}-v{i + 1}"
            variant.parent_design_id = d.design_id
            style = STYLE_MODIFIERS[i % len(STYLE_MODIFIERS)]
            variant.prompt = f"{d.prompt}, {style}"
            variant.brief["variant_style"] = style
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


def run_live_batch_stream(
    k: int = 6,
    team_niches: int = 2,
    team_size: int = 3,
    manager_auto_publish: bool = False,
    auto_publish_threshold: float = 0.85,
    image_assessor=None,
):
    """Same pipeline as run_live_batch(), but yields a progress event after
    each agent stage completes so a UI can show the real agents working
    live, stage by stage, instead of just a final result. Every stage here
    is the *same* agent function used by the simulation (app/sim/agents.py,
    app/sim/manager.py) — only the image stage swaps in real OpenAI
    generation, and two new stages (etsy, printful) do real API calls that
    don't exist in pure simulation mode.

    Real AI images cost real money, so the Manager's full review (trend,
    compliance, mockup, pricing, and the final greenlight score) now runs
    BEFORE any image is generated. Only designs the Manager has actually
    greenlit — capped at k, best score first — get a real OpenAI image. No
    credits are spent on candidates that get dropped along the way.

    team_niches/team_size: among the greenlit designs, the top `team_niches`
    trending niches each get a small "art team" of `team_size` style
    variants generated in parallel (see _build_image_team), instead of a
    single design, so you have real options to pick from. This increases
    real OpenAI spend proportionally — set team_size=1 or team_niches=0 to
    disable and go back to one image per design.

    manager_auto_publish: if True, the Manager (Dr. Cypher) will publish an
    Etsy listing live immediately — no human click needed — for any
    greenlit design whose manager score is >= auto_publish_threshold.
    Everything else still lands in the pending-approval queue for you to
    review and publish manually, exactly as before. You remain the fallback
    for anything the Manager isn't confident enough to decide on its own.

    Art quality: prompts are written from structured, product-aware briefs
    and pass an explainable text-only concept pre-check (bounded rework)
    BEFORE the greenlight — this is concept approval, not image approval.
    After generation each image gets a separate image assessment (offline
    file checks, or ``image_assessor`` if you pass one). Images are never
    auto-regenerated: at most one paid image per greenlit design/variant.

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
    product_types = tuple(config["product_types"])
    prompt_agent_live(designs, product_types=product_types)
    quality = refine_designs(designs, product_types=product_types)
    yield {
        "stage": "prompt",
        "status": "done",
        "message": f"Wrote {len(designs)} brief-based prompt(s); concept pre-check passed {quality['passed']}, "
        f"reworked {quality['revised']} time(s), blocked {quality['blocked']} (text-only check, no image yet).",
        "count": len(designs),
    }

    yield {"stage": "compliance", "status": "active", "message": "Checking for trademark/brand similarity risk (no image needed yet)..."}
    compliance_agent(designs)
    manager.review_compliance(
        designs,
        recheck=compliance_agent,
        revise=lambda d: revise_for_compliance(d, product_types=product_types),
    )
    passed = sum(1 for d in designs if d.compliance_status == "pass")
    yield {
        "stage": "compliance",
        "status": "done",
        "message": f"{passed}/{len(designs)} passed compliance.",
        "count": passed,
    }

    yield {"stage": "mockup", "status": "active", "message": "Assigning product mockups (mug/tshirt/tote)..."}
    mockup_agent(designs, product_types=product_types)
    yield {"stage": "mockup", "status": "done", "message": f"Mocked up {len(designs)} product(s).", "count": len(designs)}

    yield {"stage": "pricing", "status": "active", "message": "Pricing for target margin..."}
    pricing_agent(designs, target_margin=config["target_margin"])
    manager.review_pricing(designs)
    yield {"stage": "pricing", "status": "done", "message": f"Priced {len(designs)} design(s).", "count": len(designs)}

    yield {"stage": "manager", "status": "active", "message": "Manager scoring and making the greenlight call (before spending on art)..."}
    manager.score_and_decide(designs)
    approved = [d for d in designs if d.approved]
    approved.sort(key=lambda d: manager.score_for(d).get("score", 0.0), reverse=True)
    greenlit = approved[:k]
    yield {
        "stage": "manager",
        "status": "done",
        "message": f"Dr. Cypher concept-greenlit {len(greenlit)}/{len(designs)} design(s) for real listing — only these "
        f"will get real art. {len(designs) - len(approved)} concept-only rejection(s) have no image and are not "
        "sent to recycling.",
        "count": len(greenlit),
    }

    before_team = len(greenlit)
    greenlit = _build_image_team(greenlit, team_niches=team_niches, team_size=team_size)
    added = len(greenlit) - before_team
    if added > 0:
        yield {
            "stage": "image_team",
            "status": "done",
            "message": f"Assembled art teams of {team_size} on the top {team_niches} greenlit niche(s) "
            f"(+{added} style variant(s) to generate).",
            "count": len(greenlit),
        }

    if openai_image.is_configured():
        yield {"stage": "image", "status": "active", "message": f"Generating {len(greenlit)} real AI image(s) via OpenAI for the greenlit design(s) only (in parallel)..."}
    else:
        yield {
            "stage": "image",
            "status": "active",
            "message": "OPENAI_API_KEY not set — falling back to simulated image URIs.",
        }
    for finished in openai_image.image_agent_live_stream(greenlit):
        finished.quality["image"] = assess_generated_image(finished, assessor=image_assessor)
        _append_image_manifest(finished, manager)
        yield {
            "stage": "image",
            "status": "active",
            "message": f"{finished.design_id} ({finished.niche}) art finished.",
            "design_id": finished.design_id,
            "image_uri": finished.image_uri,
        }
    yield {"stage": "image", "status": "done", "message": f"Generated {len(greenlit)} image(s) — none wasted on dropped designs.", "count": len(greenlit)}

    yield {
        "stage": "etsy",
        "status": "active",
        "message": f"Creating {len(greenlit)} real Etsy DRAFT listing(s) (not public)...",
    }
    queued = []
    printful_count = 0
    auto_published = 0
    for design in greenlit:
        entry = _stage_design(design, shop)
        score = manager.score_for(design).get("score", 0.0)
        if manager_auto_publish and score >= auto_publish_threshold:
            etsy_client.publish_listing(
                entry["etsy_shop_id"], entry["etsy_listing_id"], return_policy_id=shop["return_policy_id"]
            )
            entry["status"] = "live"
            entry["published_by"] = "manager"
            auto_published += 1
        else:
            entry["published_by"] = None
        queued.append(entry)
        if entry.get("printful_sync_product"):
            printful_count += 1
    yield {
        "stage": "etsy",
        "status": "done",
        "message": f"Created {len(queued)} draft listing(s) on Etsy.",
        "count": len(queued),
    }
    if manager_auto_publish:
        remaining = len(queued) - auto_published
        yield {
            "stage": "manager_publish",
            "status": "done",
            "message": f"Manager (Dr. Cypher) auto-published {auto_published} design(s) with score >= {auto_publish_threshold} live. "
            f"{remaining} design(s) below that bar are waiting for your review in Pending Approvals.",
            "count": auto_published,
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


PRODUCT_TAG_SYNONYMS = {
    "mug": ["coffee mug", "mug gift", "ceramic mug"],
    "tshirt": ["graphic tee", "t shirt", "unisex shirt"],
    "tote": ["tote bag", "canvas tote", "reusable bag"],
}


def _generate_tags(niche: str, product_type: str) -> List[str]:
    """Auto-fills the "Attributes > Tags" field of the Etsy listing form —
    the one piece of the create-listing UI this pipeline didn't already
    cover (title/description/category/price/shipping/how-it's-made are all
    set directly from the design). Etsy allows up to 13 tags, max 20
    characters each; buyers search almost entirely by these."""
    niche_words = [w for w in niche.lower().replace("-", " ").split() if w]
    tags: List[str] = []
    tags.append(niche.lower()[:20])
    tags.extend(niche_words)
    tags.extend(PRODUCT_TAG_SYNONYMS.get(product_type, [product_type]))
    tags.extend(["gift idea", "unique design", "custom print", "made to order", "trendy gift"])
    seen = set()
    deduped = []
    for t in tags:
        t = t.strip()[:20]
        if t and t not in seen:
            seen.add(t)
            deduped.append(t)
        if len(deduped) == 13:
            break
    return deduped


def _attach_mockup(design_id, product_type, shop_id, listing_id, etsy_image_url, flat_design_image_id):
    """Best-effort: generate a realistic product photo (design applied to an
    actual rendered mug/shirt/tote) via Printful's Mockup Generator API and
    upload it as the primary (rank=1) Etsy photo, so buyers see the real
    product instead of just the flat printed artwork. The flat design
    stays in the listing too (bumped to rank=2) and remains the file
    Printful actually prints from. Returns (temporary Printful mockup URL,
    local mockup path), or (None, None) if anything fails -- the flat design
    image is already on the listing, so a failure never breaks staging."""
    printful_product_id = PRODUCT_PRINTFUL_PRODUCT.get(product_type)
    variant_id = PRODUCT_PRINTFUL_VARIANT.get(product_type)
    if not (printful_client.is_configured() and etsy_image_url and printful_product_id and variant_id):
        return None, None
    mockup_url = printful_client.generate_mockup(printful_product_id, variant_id, etsy_image_url)
    if not mockup_url:
        return None, None
    mockup_path = DATA_DIR / "images" / f"{design_id}_mockup.jpg"
    try:
        resp = requests.get(mockup_url, timeout=30)
        resp.raise_for_status()
        mockup_path.parent.mkdir(parents=True, exist_ok=True)
        mockup_path.write_bytes(resp.content)
        etsy_client.upload_listing_image(shop_id, listing_id, str(mockup_path))
    except Exception:
        return None, None
    if flat_design_image_id:
        try:
            etsy_client.reorder_listing_image(shop_id, listing_id, flat_design_image_id, rank=2)
        except Exception:
            pass  # the mockup is already on the listing; don't re-upload it on a later refresh
    return mockup_url, str(mockup_path)


def refresh_mockups(design_id: Optional[str] = None) -> List[dict]:
    """Backfills product photos for already-staged listings (pending or
    live) that only have the flat artwork -- e.g. totes/t-shirts staged
    before apparel mockups generated reliably. Adds the mockup as the
    primary Etsy photo, bumps the flat art to rank 2, and sets it as the
    Printful sync product's preview. Best-effort per entry; entries whose
    mockup still can't be generated are left untouched. Returns the
    entries that got a new mockup."""
    pending = _load_pending()
    refreshed = []
    for entry in pending:
        if design_id is not None and entry.get("design_id") != design_id:
            continue
        if entry.get("mockup_image_url") or entry.get("status") not in ("pending_approval", "live"):
            continue
        flat_image_id = entry.get("etsy_flat_image_id")
        if not flat_image_id and printful_client.is_configured():
            try:
                images = etsy_client.get_listing_images(entry["etsy_listing_id"])
                flat = next((i for i in images if i.get("url_fullxfull") == entry.get("etsy_image_url")), None)
                flat_image_id = (flat or min(images, key=lambda i: i.get("rank", 99))).get("listing_image_id")
            except Exception:
                flat_image_id = None
        mockup_url, mockup_uri = _attach_mockup(
            entry["design_id"], entry.get("product_type"), entry.get("etsy_shop_id"),
            entry.get("etsy_listing_id"), entry.get("etsy_image_url"), flat_image_id,
        )
        if not mockup_url:
            continue
        entry["mockup_image_url"] = mockup_url
        entry["mockup_image_uri"] = mockup_uri
        entry["etsy_flat_image_id"] = flat_image_id
        sync_id = (entry.get("printful_sync_product") or {}).get("id")
        if sync_id:
            try:
                printful_client.set_sync_product_preview(sync_id, entry["etsy_image_url"], mockup_url)
            except Exception:
                pass  # Etsy already shows the mockup; the Printful preview is a nice-to-have
        refreshed.append(entry)
    if refreshed:
        _save_pending(pending)
    return refreshed


def _stage_design(design, shop: Dict) -> dict:
    taxonomy_id = PRODUCT_TAXONOMY.get(design.product_type)
    if taxonomy_id is None:
        raise RuntimeError(f"No Etsy taxonomy mapping for product_type={design.product_type!r}")
    ship_dims = PRODUCT_SHIP_DIMENSIONS.get(design.product_type, {})
    catalog = PRODUCT_CATALOG_DETAILS.get(design.product_type, {})
    product_name = catalog.get("name", design.product_type.title())
    description = design.prompt
    if catalog:
        description += f"\n\n{product_name} — {catalog['size']}."

    listing = etsy_client.create_draft_listing(
        shop["shop_id"],
        {
            "quantity": 100,
            "title": f"{design.niche.title()} Design — {product_name}"[:140],
            "description": description,
            "price": design.price,
            "who_made": "i_did",
            "when_made": "made_to_order",
            "taxonomy_id": taxonomy_id,
            "shipping_profile_id": shop["shipping_profile_id"],
            "readiness_state_id": shop["readiness_state_id"],
            "return_policy_id": shop["return_policy_id"],
            "is_supply": False,
            "item_weight_unit": "oz",
            "item_dimensions_unit": "in",
            "tags": _generate_tags(design.niche, design.product_type),
            **ship_dims,
        },
    )
    listing_id = listing["listing_id"]

    etsy_image_url = None
    flat_design_image_id = None
    if design.image_uri and Path(design.image_uri).exists():
        image_resp = etsy_client.upload_listing_image(shop["shop_id"], listing_id, design.image_uri)
        etsy_image_url = image_resp.get("url_fullxfull") or image_resp.get("url_570xN")
        flat_design_image_id = image_resp.get("listing_image_id")

    mockup_image_url, mockup_image_uri = _attach_mockup(
        design.design_id, design.product_type, shop["shop_id"], listing_id, etsy_image_url, flat_design_image_id
    )

    printful_product = None
    if printful_client.is_configured() and etsy_image_url:
        variant_id = PRODUCT_PRINTFUL_VARIANT.get(design.product_type)
        if variant_id:
            printful_product = printful_client.create_sync_product(
                name=f"{design.design_id}-{catalog.get('name', design.product_type)}",
                variant_id=variant_id,
                image_url=etsy_image_url,
                retail_price=f"{design.price:.2f}",
                preview_image_url=mockup_image_url,
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
        "mockup_image_url": mockup_image_url,
        "mockup_image_uri": mockup_image_uri,
        "etsy_flat_image_id": flat_design_image_id,
        "printful_sync_product": printful_product,
        "status": "pending_approval",
        "trend_score": design.trend_score,
        "compliance_status": design.compliance_status,
        "compliance_notes": design.compliance_notes,
        "brief": design.brief,
        "quality": design.quality,
        "parent_design_id": design.parent_design_id or None,
        "lineage": design.lineage,
    }


def approve_and_publish(design_id: str) -> dict:
    """Human fallback approval action: publishes the Etsy draft listing
    live. Used for anything the Manager didn't auto-publish on its own
    (see manager_auto_publish on run_live_batch_stream)."""
    pending = _load_pending()
    for entry in pending:
        if entry["design_id"] == design_id and entry["status"] == "pending_approval":
            shop = _get_shop_context()
            etsy_client.publish_listing(
                entry["etsy_shop_id"], entry["etsy_listing_id"], return_policy_id=shop["return_policy_id"]
            )
            entry["status"] = "live"
            entry["published_by"] = "human"
            _save_pending(pending)
            return entry
    raise ValueError(f"No pending approval found for design_id={design_id!r}")


def reject(design_id: str, reason: str = "rejected by human reviewer") -> dict:
    """Rejects a pending design (its Etsy listing stays a draft) and delivers
    its already-generated image to the Recycling Facility once, with
    provenance. The image file is never deleted and no new image is made."""
    pending = _load_pending()
    for entry in pending:
        if entry["design_id"] == design_id and entry["status"] == "pending_approval":
            entry["status"] = "rejected"
            entry["rejection_reason"] = reason
            record = _recycle_live_entry(entry, rejected_by="human", reason=reason)
            entry["recycling_record_id"] = record["record_id"] if record else None
            _save_pending(pending)
            return entry
    raise ValueError(f"No pending approval found for design_id={design_id!r}")


def _recycle_live_entry(entry: dict, rejected_by: str, reason: str, provenance: dict = None):
    store = _recycling_store()
    record, outcome = store.enqueue(
        entry, rejected_by=rejected_by, reason=reason, source="live", source_ref="live",
        stage="human_review", provenance=provenance or {
            "etsy_listing_id": entry.get("etsy_listing_id"),
            "etsy_shop_id": entry.get("etsy_shop_id"),
            "pipeline_source": entry.get("source", "live_batch"),
        },
    )
    if record and outcome == "created" and record["status"] == recycling.PENDING_ANALYSIS:
        store.analyze(record["record_id"], _live_recycling_context(), recycler_id="recycler-1",
                      images_root=IMAGES_DIR)
    store.save()
    return record


def hold_archive_image_for_reuse(design_id: str) -> dict:
    """Send an Image Archive entry (including orphaned files with no
    manifest record) to the Recycling Facility for cross-referencing."""
    entry = next((e for e in list_image_archive() if e["design_id"] == design_id), None)
    if entry is None:
        raise ValueError(f"No archived image for design_id={design_id!r}")
    orphan = entry.get("niche") is None
    return _recycle_live_entry(
        dict(entry, compliance_status=entry.get("compliance_status") or ("pending" if orphan else "pass")),
        rejected_by="human",
        reason="held for reuse from the image archive" + (" (orphan file, no metadata)" if orphan else ""),
        provenance={"pipeline_source": "image_archive", "orphan": orphan,
                    "generated_at": entry.get("generated_at"), "manager_score": entry.get("manager_score")},
    )


def stage_recycled_candidate(record_id: str) -> dict:
    """Turns a reuse-requested Recycling Facility record into a *new* Etsy
    DRAFT using the existing image (no new image generation). The candidate
    must pass the current compliance check, concept check, pricing and the
    Manager's score; it is then queued for explicit human approval and is
    never auto-published. Blocked candidates are recorded and not staged."""
    store = _recycling_store()
    record = store.get(record_id)
    if record["status"] == recycling.REENTERED:
        return {"status": "already_reentered", "record": record}
    if record["source"] != "live" or record["asset_kind"] != "generated_image":
        raise ValueError("Only live, actually generated images can be staged from recycling.")
    if recycling.safe_image_path(record["image_uri"], IMAGES_DIR) is None:
        raise ValueError("Original image file is missing or outside data/images; nothing to reuse.")
    design = store.build_candidate(record_id)
    if any(e["design_id"] == design.design_id for e in _load_pending()):
        raise ValueError(f"design_id={design.design_id!r} has already been staged once.")

    config = load_etsy_config()
    compliance_agent([design])
    design.quality["concept"] = assess_concept(design)
    design.unit_cost = PRODUCT_UNIT_COSTS.get(design.product_type, 7.0)
    pricing_agent([design], target_margin=config.get("target_margin", 0.42))
    manager = ManagerAgent()
    manager.review_pricing([design])
    manager.score_and_decide([design])
    decision = manager.score_for(design).get("manager_decision", "BLOCK")
    gates = {
        "compliance": design.compliance_status,
        "quality": design.quality["concept"]["status"],
        "pricing": f"${design.price:.2f}",
        "manager": decision,
    }
    if decision == "BLOCK":
        store.mark_reentered(record_id, "live:blocked", dict(gates, human_approval="not reached"))
        store.save()
        return {"status": "blocked", "gates": gates, "record": record}

    entry = _stage_design(design, _get_shop_context())
    entry["published_by"] = None  # never auto-published
    entry["source"] = "recycling"
    pending = _load_pending()
    pending.append(entry)
    _save_pending(pending)
    store.mark_reentered(record_id, "live:etsy_draft", dict(gates, human_approval="pending (Live Ops)"))
    store.save()
    return {"status": "staged", "gates": gates, "entry": entry}


def stage_recycled_sticker(record_id: str) -> dict:
    """Create a Printful-backed Etsy draft after recycler-team and agent approval."""
    store = _recycling_store()
    record = store.get(record_id)
    workflow = record.get("sticker_workflow") or {}
    if workflow.get("status") == "staged":
        entry = next((e for e in _load_pending() if e.get("recycling_record_id") == record_id), None)
        return {"status": "already_staged", "entry": entry, "record": record}
    record = sticker_team.validate_sticker_approval(store, record_id, IMAGES_DIR)
    missing = sticker_configuration_errors()
    if missing:
        raise ValueError("Configure these sticker product settings before staging: " + ", ".join(missing))
    if not printful_client.is_configured():
        raise ValueError("Set PRINTFUL_API_KEY before creating a Printful sticker product.")

    design_id = f"{record['source_design_id']}-STICKER-{record_id[3:9]}"
    if any(e.get("design_id") == design_id for e in _load_pending()):
        raise ValueError(f"design_id={design_id!r} has already been staged.")
    config = load_etsy_config()
    original = record.get("original") or {}
    design = Design(
        design_id=design_id,
        niche=original.get("niche") or "recycled art",
        trend_score=float(original.get("trend_score") or 0.5),
        prompt=original.get("prompt") or f"Die-cut sticker from recycled artwork {record['source_design_id']}",
        image_uri=record["image_uri"],
        compliance_status="pending",
        product_type="sticker",
        unit_cost=PRODUCT_UNIT_COSTS["sticker"],
        parent_design_id=record["source_design_id"],
        lineage={"recycled_from": record_id, "product": "die_cut_sticker"},
        brief=original.get("brief") or {},
    )
    compliance_agent([design])
    design.quality["concept"] = assess_concept(design)
    pricing_agent([design], target_margin=config.get("target_margin", 0.42))
    manager = ManagerAgent()
    manager.review_pricing([design])
    manager.score_and_decide([design])
    decision = manager.score_for(design).get("manager_decision", "BLOCK")
    gates = {
        "compliance": design.compliance_status,
        "quality": design.quality["concept"]["status"],
        "pricing": f"${design.price:.2f}",
        "manager": decision,
    }
    if decision == "BLOCK":
        workflow.update(status="rejected", production_gates=gates)
        record["sticker_workflow"] = workflow
        record["history"].append({
            "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "action": "sticker_production_blocked", "by": "system",
            "note": f"Fresh production gates blocked this candidate: {gates}",
        })
        store.save()
        return {"status": "blocked", "gates": gates, "record": record}

    entry = _stage_design(design, _get_shop_context())
    entry.update(
        published_by=None,
        source="recycling_sticker",
        recycling_record_id=record_id,
        production_gates=gates,
    )
    pending = _load_pending()
    pending.append(entry)
    _save_pending(pending)
    workflow.update(status="staged", production_gates=gates, design_id=design_id)
    record["sticker_workflow"] = workflow
    record["history"].append({
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "action": "sticker_draft_staged", "by": "system",
        "note": f"{design_id} queued as an Etsy draft; human publishing approval is still required.",
    })
    store.save()
    return {"status": "staged", "gates": gates, "entry": entry}


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
    run_p.add_argument(
        "--manager-auto-publish",
        action="store_true",
        help="Let the Manager (Dr. Cypher) publish its own highest-confidence designs live, no human click needed",
    )
    run_p.add_argument(
        "--auto-publish-threshold",
        type=float,
        default=0.85,
        help="Manager score (0-1) required for an auto-publish decision",
    )

    approve_p = sub.add_parser("approve", help="Publish a pending design's Etsy listing live")
    approve_p.add_argument("design_id")

    reject_p = sub.add_parser(
        "reject", help="Reject a pending design (leaves Etsy listing as draft; image goes to recycling)"
    )
    reject_p.add_argument("design_id")
    reject_p.add_argument("--reason", default="rejected by human reviewer")

    sub.add_parser("list", help="List pending approvals")

    refresh_p = sub.add_parser(
        "refresh-mockups",
        help="Add a product mockup photo to existing listings that only show the flat artwork",
    )
    refresh_p.add_argument("design_id", nargs="?", default=None)

    args = p.parse_args()
    if args.action == "run-batch":
        queued = []
        for event in run_live_batch_stream(
            k=args.k,
            team_niches=args.team_niches,
            team_size=args.team_size,
            manager_auto_publish=args.manager_auto_publish,
            auto_publish_threshold=args.auto_publish_threshold,
        ):
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
        entry = reject(args.design_id, reason=args.reason)
        print(f"Rejected: {entry}")
    elif args.action == "list":
        for entry in list_pending():
            print(entry)
    elif args.action == "refresh-mockups":
        refreshed = refresh_mockups(args.design_id)
        print(f"Added mockup photos to {len(refreshed)} listing(s): {[e['design_id'] for e in refreshed]}")


if __name__ == "__main__":
    main()
