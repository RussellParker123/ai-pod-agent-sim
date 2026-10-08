import argparse
import json
import logging
from pathlib import Path

from app.connectors.etsy_connector import (
    EtsyConnector,
    configure_etsy_logging,
)
from app.sim.agents import (
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
from app.sim.utils import DATA_DIR, save_json, timestamp
from app.sim.team import AgentTeam
from app.sim.approvals import final_review_status, load_review_overrides


log = logging.getLogger(__name__)


def run_once(
    etsy_mode: bool = False,
    real: bool = False,
    draft_only: bool = False,
    team: AgentTeam = None,
) -> str:
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

    niches = [
        "cozy autumn",
        "pet lovers",
        "minimalist motivation",
        "retro outdoors",
        "bookish humor",
        "coffee culture",
    ]
    team = team or AgentTeam()
    manager = ManagerAgent(manager_id=team.manager_id)

    research = research_agent(niches, etsy_connector=etsy_connector)
    designs = trend_agent(niches=niches, k=24, etsy_connector=etsy_connector)
    apply_research(designs, research)  # research -> trend/prompt departments
    designs = manager.review_trends(designs)

    team.run_stage("prompt", designs, prompt_agent)
    team.run_stage("image", designs, image_agent)
    compliance_check = lambda items: compliance_agent(
        items, etsy_connector=etsy_connector
    )
    team.run_stage("compliance", designs, compliance_check)
    manager.review_compliance(designs, recheck=compliance_check)

    team.run_stage(
        "mockup",
        designs,
        mockup_agent,
        preferred_product_types=research["top_product_types"],
    )
    pricing_research = pricing_research_agent(etsy_connector=etsy_connector)
    market_prices = {
        product: details["median_price"]
        for product, details in pricing_research["benchmarks"].items()
    }
    team.run_stage(
        "pricing",
        designs,
        pricing_agent,
        target_margin=0.40,
        market_prices=market_prices,
    )
    manager.review_pricing(designs)
    if "marketing" in team.workers:
        team.run_stage("marketing", designs, marketing_agent)
    manager.score_and_decide(designs)  # GREENLIGHT / HOLD / BLOCK + batch status

    results = listing_simulator(designs)
    payload = to_serializable(designs, results)
    payload["research"] = research
    payload["pricing_research"] = pricing_research
    payload["manager"] = manager.report(designs, results)
    payload["team"] = team.report()

    if real or draft_only:
        from app.marketplace.adapter import get_adapter

        adapter = get_adapter("etsy", draft_only=draft_only)
        listings = []
        for d in designs:
            if d.approved:
                info = adapter.list_design(d, real=real)
                listings.append({"design_id": d.design_id, **info})
                log.info("Listing %s: %s %s (%s)", d.design_id, info["mode"], info["listing_id"], info["status"])
        payload["marketplace_listings"] = listings

    path = save_json(payload, f"run_{timestamp()}.json")
    return str(path)


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
    parser = argparse.ArgumentParser(description="Run the AI POD agent simulation.")
    parser.add_argument(
        "--etsy-mode",
        action="store_true",
        help="Use read-only Etsy store data when credentials are configured.",
    )
    parser.add_argument("--real", action="store_true", help="publish approved designs to Etsy (default: simulate)")
    parser.add_argument("--draft-only", action="store_true", help="save listings as drafts instead of active")
    parser.add_argument(
        "--publish-run",
        help="publish a previously reviewed run; requires saved per-design approvals",
    )
    parser.add_argument("--yes", action="store_true", help="skip the confirmation prompt for --real")
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
        p = run_once(etsy_mode=args.etsy_mode, real=real, draft_only=args.draft_only)
    print(f"Simulation complete. Output: {p}")
