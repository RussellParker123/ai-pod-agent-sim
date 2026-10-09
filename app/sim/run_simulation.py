import argparse
import json
import logging
import random
from dataclasses import asdict
from pathlib import Path
from typing import List, Optional

from app.connectors.etsy_connector import (
    EtsyConnector,
    configure_etsy_logging,
)
from app.sim.agents import (
    Design,
    ListingResult,
    trend_agent,
    prompt_agent,
    image_agent,
    compliance_agent,
    mockup_agent,
    pricing_agent,
    listing_simulator,
    to_serializable,
)
from app.sim.research import research_agent, apply_research, pricing_research_agent
from app.sim.marketing import marketing_agent
from app.sim.manager import ManagerAgent
from app.sim.utils import save_json, timestamp, DATA_DIR
from app.sim.team import AgentTeam, load_team_state, save_team_state
from app.sim.approvals import final_review_status, load_review_overrides
from app.sim.art_quality import assess_generated_image, refine_designs, revise_for_compliance
from app.sim import recycling

log = logging.getLogger(__name__)

DEFAULT_NICHES = [
    "cozy autumn",
    "pet lovers",
    "minimalist motivation",
    "retro outdoors",
    "bookish humor",
    "coffee culture",
    "western desert",
]
DEFAULT_PRODUCT_TYPES = ("mug", "tshirt", "tote")
DEFAULT_MARGIN = 0.42

ETSY_CONFIG_PATH = DATA_DIR / "etsy_config.json"
TEAM_STATE_FILENAME = "team_state.json"
MAX_REUSE_PER_RUN = 6
DEFAULT_BATCH_SIZE = 24
MAX_BATCH_SIZE = 200


def load_etsy_config() -> dict:
    if not ETSY_CONFIG_PATH.exists():
        raise SystemExit(
            f"--etsy-mode requires {ETSY_CONFIG_PATH} to exist. Run:\n"
            "    python -m app.setup.etsy_wizard\n"
            "first to generate it."
        )
    with open(ETSY_CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def apply_etsy_fees(designs: List[Design], results: List[ListingResult], fees: dict) -> None:
    """Deducts Etsy's real fee structure from each result's profit, in place:
    - listing_fee: charged once per listing that actually went live (approved)
    - transaction_fee_pct: percent of revenue, charged on sales
    - payment_fee_pct / payment_fee_flat: payment processing, charged per order
    """
    listing_fee = fees.get("listing_fee", 0.0)
    transaction_fee_pct = fees.get("transaction_fee_pct", 0.0) / 100.0
    payment_fee_pct = fees.get("payment_fee_pct", 0.0) / 100.0
    payment_fee_flat = fees.get("payment_fee_flat", 0.0)

    by_id = {d.design_id: d for d in designs}
    for r in results:
        design = by_id.get(r.design_id)
        if not design or not design.approved:
            continue
        transaction_fee = r.revenue * transaction_fee_pct
        payment_fee = (r.revenue * payment_fee_pct) + (r.orders * payment_fee_flat)
        total_fees = listing_fee + transaction_fee + payment_fee
        r.profit = round(r.profit - total_fees, 2)


def run_once(
    etsy_mode: bool = False,
    real: bool = False,
    draft_only: bool = False,
    team: AgentTeam = None,
    batch_size: int = DEFAULT_BATCH_SIZE,
    seed: Optional[int] = None,
) -> str:
    """Run one batch and save ``data/run_*.json``. ``batch_size`` is the
    number of candidate designs the trend agent proposes; ``seed`` makes the
    simulated (offline) randomness reproducible."""
    batch_size = int(batch_size)
    if not 1 <= batch_size <= MAX_BATCH_SIZE:
        raise ValueError(f"batch_size must be between 1 and {MAX_BATCH_SIZE}")
    if seed is not None:
        random.seed(int(seed))
    niches = DEFAULT_NICHES
    product_types = DEFAULT_PRODUCT_TYPES
    target_margin = DEFAULT_MARGIN
    etsy_config: Optional[dict] = None

    if etsy_mode:
        if ETSY_CONFIG_PATH.exists():
            etsy_config = load_etsy_config()
            niches = etsy_config.get("niches") or niches
            product_types = tuple(etsy_config.get("product_types") or product_types)
            target_margin = etsy_config.get("target_margin", target_margin)

    configure_etsy_logging(DATA_DIR / "etsy_api.log")
    etsy_connector = EtsyConnector.from_environment() if etsy_mode else None
    if etsy_connector:
        logging.getLogger("app.connectors.etsy_connector").info(
            "Etsy integration enabled for shop %s", etsy_connector.shop_id
        )
    else:
        logging.getLogger("app.connectors.etsy_connector").info(
            "Etsy integration unavailable; using mock behavior"
        )

    # A custom team is used as-is; otherwise the persisted roster is loaded so
    # user transfers (Office page) change who does the work in this run.
    persist_team = team is None
    team_state_path = DATA_DIR / TEAM_STATE_FILENAME
    team = team or load_team_state(team_state_path)
    manager = ManagerAgent(manager_id=team.manager_id)
    run_name = _unique_run_name()
    store = recycling.RecyclingStore(DATA_DIR / recycling.RECYCLING_FILENAME)

    research = research_agent(niches, etsy_connector=etsy_connector)
    designs = trend_agent(niches=niches, k=batch_size, etsy_connector=etsy_connector)
    apply_research(designs, research)  # research -> trend/prompt departments
    candidates = list(designs)
    designs = manager.review_trends(designs)
    kept_ids = {d.design_id for d in designs}
    # Dropped before any image existed: concept-only, never sent to recycling.
    skipped_no_image = [d.design_id for d in candidates if d.design_id not in kept_ids]

    # Previously rejected art a human asked to reuse: same image, fresh gates.
    reuse_designs = []
    for record in store.records:
        if (record["status"] == recycling.REUSE_REQUESTED and record["source"] == "simulation"
                and len(reuse_designs) < MAX_REUSE_PER_RUN):
            reuse_designs.append(store.build_candidate(record["record_id"]))

    quality_summary = {"checked": 0, "revised": 0, "passed": 0, "blocked": 0, "needs_revision": 0}

    def write_and_refine(items):
        prompt_agent(items, research=research, product_types=product_types)
        for key, value in refine_designs(items, research=research, product_types=product_types).items():
            quality_summary[key] += value

    team.run_stage("prompt", designs, write_and_refine)
    team.run_stage("image", designs, image_agent)
    refine_designs(reuse_designs)  # assess only: recycled pixels can't be re-prompted
    all_designs = designs + reuse_designs
    compliance_check = lambda items: compliance_agent(
        items, etsy_connector=etsy_connector
    )
    team.run_stage("compliance", all_designs, compliance_check)
    manager.review_compliance(
        all_designs,
        recheck=compliance_check,
        revise=lambda d: revise_for_compliance(d, research=research, product_types=product_types),
    )

    team.run_stage(
        "mockup",
        all_designs,
        mockup_agent,
        product_types=product_types,
        preferred_product_types=research["top_product_types"],
    )
    pricing_research = pricing_research_agent(etsy_connector=etsy_connector)
    market_prices = {
        product: details["median_price"]
        for product, details in pricing_research["benchmarks"].items()
    }
    team.run_stage(
        "pricing",
        all_designs,
        pricing_agent,
        target_margin=target_margin,
        market_prices=market_prices,
    )
    manager.review_pricing(all_designs)
    if "marketing" in team.workers:
        team.run_stage("marketing", all_designs, marketing_agent)
    manager.score_and_decide(all_designs)  # GREENLIGHT / HOLD / BLOCK + batch status
    for d in all_designs:
        d.quality["image"] = assess_generated_image(d)

    recycling_summary = _recycle_rejections(
        all_designs, manager, team, store, research, product_types, run_name
    )
    recycling_summary["skipped_no_image"] = skipped_no_image
    for candidate in reuse_designs:
        decision = manager.score_for(candidate).get("manager_decision", "BLOCK")
        store.mark_reentered(candidate.lineage["recycled_from"], run_name, {
            "compliance": candidate.compliance_status,
            "quality": candidate.quality.get("concept", {}).get("status", "not_run"),
            "pricing": f"${candidate.price:.2f}",
            "manager": decision,
            "human_approval": "pending (Review page)",
        })
    recycling_summary["reentered"] = [d.design_id for d in reuse_designs]
    recycling_summary["counts"] = store.counts()
    store.save()
    manager.character.return_home()

    results = listing_simulator(all_designs)
    if etsy_mode and etsy_config:
        apply_etsy_fees(all_designs, results, etsy_config.get("fees", {}))

    payload = to_serializable(all_designs, results)
    payload["research"] = research
    payload["pricing_research"] = pricing_research
    payload["manager"] = manager.report(all_designs, results)
    payload["quality"] = quality_summary
    payload["recycling"] = recycling_summary
    if etsy_mode:
        payload["etsy_mode"] = True
        payload["etsy_config"] = etsy_config
    team.release_temporary()
    payload["team"] = team.report()
    if persist_team:
        save_team_state(team, team_state_path)

    if real or draft_only:
        from app.marketplace.adapter import get_adapter

        adapter = get_adapter("etsy", draft_only=draft_only)
        listings = []
        for d in all_designs:
            # Recycled reuse candidates are never auto-listed: they need an
            # explicit Review-page approval (publish_reviewed_run).
            if d.approved and not d.lineage.get("recycled_from"):
                info = adapter.list_design(d, real=real)
                listings.append({"design_id": d.design_id, **info})
                log.info("Listing %s: %s %s (%s)", d.design_id, info["mode"], info["listing_id"], info["status"])
        payload["marketplace_listings"] = listings

    path = save_json(payload, run_name)
    return str(path)


def _unique_run_name() -> str:
    """``run_<timestamp>.json``; a second run in the same second gets a
    suffix instead of overwriting the earlier run."""
    stamp = timestamp()
    name, n = f"run_{stamp}.json", 2
    while (DATA_DIR / name).exists():
        name, n = f"run_{stamp}_{n}.json", n + 1
    return name


def _recycle_rejections(designs, manager, team, store, research, product_types, run_name) -> dict:
    """Deliver manager/compliance-rejected art (which already has an image)
    to the Recycling Facility, then let the recycling department analyse it."""
    enqueued, duplicates, records = [], 0, []
    for d in designs:
        scoring = manager.score_for(d)
        if scoring.get("manager_decision") != "BLOCK":
            continue
        by = "compliance" if d.compliance_status != "pass" else "manager"
        reason = "; ".join(scoring.get("reasons") or []) or "blocked by manager"
        record, outcome = store.enqueue(
            asdict(d), rejected_by=by, reason=reason, source="simulation", source_ref=run_name,
            stage="compliance" if by == "compliance" else "approval",
            provenance={"run": run_name, "manager_score": scoring.get("score"),
                        "manager_decision": "BLOCK", "image_kind": "simulated"},
        )
        if outcome == "created":
            enqueued.append(record["record_id"])
        elif outcome == "duplicate":
            duplicates += 1
        if record:
            records.append(record)

    pending = [r for r in records if r["status"] == recycling.PENDING_ANALYSIS]
    moves = []
    if pending and "recycling" in team.workers:
        moves = team.rebalance({"recycling": len(pending)})
        context = recycling.build_context(
            research=research,
            approved_designs=[asdict(d) for d in designs if d.approved],
            archive=_read_image_manifest(),
            product_types=product_types,
        )
        team.run_stage(
            "recycling", pending, recycling.recycler_agent, worker_kwarg="recycler_id",
            store=store, context=context,
        )
    if records:
        manager.character.visit(
            "recycling", "Delivering rejected art to the Recycling Facility",
            [r["source_design_id"] for r in records], count=len(records),
        )
    return {
        "facility": "Recycling Facility",
        "enqueued": enqueued,
        "duplicates": duplicates,
        "demand_transfers": moves,
        "records": [
            {
                "record_id": r["record_id"],
                "source_design_id": r["source_design_id"],
                "status": r["status"],
                "rejected_by": r["rejection"]["by"],
                "top_suggestion": ((r.get("analysis") or {}).get("suggestions") or [{}])[0].get("type"),
                # Snapshot of the recycler's plan at run time (the queue may change later).
                "analysis": recycling.analysis_summary(r.get("analysis")),
            }
            for r in records
        ],
        "limitations": recycling.METADATA_LIMITATIONS,
    }


def _read_image_manifest() -> list:
    path = DATA_DIR / "image_manifest.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    except (OSError, ValueError):
        return []
    return data if isinstance(data, list) else []


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Run one AI POD agent simulation batch.")
    p.add_argument(
        "--etsy-mode",
        action="store_true",
        help=(
            "Use read-only Etsy store data when credentials are configured, "
            "plus niches/product types/margin and fees from data/etsy_config.json "
            "when available."
        ),
    )
    p.add_argument("--real", action="store_true", help="publish approved designs to Etsy (default: simulate)")
    p.add_argument("--draft-only", action="store_true", help="save listings as drafts instead of active")
    p.add_argument(
        "--publish-run",
        help="publish a previously reviewed run; requires saved per-design approvals",
    )
    p.add_argument("--yes", action="store_true", help="skip the confirmation prompt for --real")
    p.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE,
                   help=f"candidate designs proposed by the trend agent (1-{MAX_BATCH_SIZE})")
    p.add_argument("--seed", type=int, default=None, help="seed for reproducible simulated randomness")
    return p


def publish_reviewed_run(
    run_name: str,
    real: bool = False,
    draft_only: bool = False,
) -> str:
    if Path(run_name).name != run_name or not run_name.startswith("run_") or not run_name.endswith(".json"):
        raise ValueError("Choose a run_*.json file from the data directory")

    run_path = DATA_DIR / run_name
    payload = json.loads(run_path.read_text(encoding="utf-8"))
    manager = payload.get("manager", {})
    scores = manager.get("design_scores", {})
    overrides = load_review_overrides(run_name, DATA_DIR / "overrides.json")
    statuses = {}
    eligible = []
    for design in payload.get("designs", []):
        design_id = design.get("design_id")
        decision = scores.get(design_id, {}).get("manager_decision", "BLOCK")
        status = final_review_status(
            decision, design.get("compliance_status", "pending"), overrides.get(design_id, "none")
        )
        statuses[design_id] = status
        if status in ("APPROVED", "FORCE_APPROVED"):
            eligible.append(design)

    from app.marketplace.adapter import get_adapter

    adapter = get_adapter("etsy", draft_only=draft_only)
    payload["review_status"] = statuses
    payload["marketplace_listings"] = [
        {"design_id": design["design_id"], **adapter.list_design(design, real=real)}
        for design in eligible
    ]
    output_path = DATA_DIR / f"published_{run_name}"
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return str(output_path)


if __name__ == "__main__":
    parser = build_arg_parser()
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    real = args.real
    if real and not args.yes:
        kind = "DRAFT" if args.draft_only else "ACTIVE"
        if input(f"Create real {kind} Etsy listings for approved designs? [y/N] ").strip().lower() != "y":
            print("Not confirmed; running in simulation mode.")
            real = False
    if args.publish_run:
        if args.real and not real:
            raise SystemExit(0)
        if not real:
            parser.error("--publish-run requires --real")
        p = publish_reviewed_run(args.publish_run, real=real, draft_only=args.draft_only)
    else:
        p = run_once(etsy_mode=args.etsy_mode, real=real, draft_only=args.draft_only,
                     batch_size=args.batch_size, seed=args.seed)
    print(f"Simulation complete. Output: {p}")
