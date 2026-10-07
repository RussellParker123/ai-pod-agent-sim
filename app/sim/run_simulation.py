import argparse
import logging

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
from app.sim.manager import ManagerAgent
from app.sim.utils import DATA_DIR, save_json, timestamp


log = logging.getLogger(__name__)


def run_once(etsy_mode: bool = False, real: bool = False, draft_only: bool = False) -> str:
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
    manager = ManagerAgent()

    designs = trend_agent(niches=niches, k=24, etsy_connector=etsy_connector)
    designs = manager.review_trends(designs)

    prompt_agent(designs)
    image_agent(designs)
    compliance_check = lambda items: compliance_agent(
        items, etsy_connector=etsy_connector
    )
    compliance_check(designs)
    manager.review_compliance(designs, recheck=compliance_check)

    mockup_agent(designs)
    pricing_agent(designs, target_margin=0.42)
    manager.review_pricing(designs)
    manager.score_and_decide(designs)  # GREENLIGHT / HOLD / BLOCK + batch status

    results = listing_simulator(designs)
    payload = to_serializable(designs, results)
    payload["manager"] = manager.report(designs, results)

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


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the AI POD agent simulation.")
    parser.add_argument(
        "--etsy-mode",
        action="store_true",
        help="Use read-only Etsy store data when credentials are configured.",
    )
    parser.add_argument("--real", action="store_true", help="publish approved designs to Etsy (default: simulate)")
    parser.add_argument("--draft-only", action="store_true", help="save listings as drafts instead of active")
    parser.add_argument("--yes", action="store_true", help="skip the confirmation prompt for --real")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    real = args.real
    if real and not args.yes:
        kind = "DRAFT" if args.draft_only else "ACTIVE"
        if input(f"Create real {kind} Etsy listings for approved designs? [y/N] ").strip().lower() != "y":
            print("Not confirmed; running in simulation mode.")
            real = False
    p = run_once(etsy_mode=args.etsy_mode, real=real, draft_only=args.draft_only)
    print(f"Simulation complete. Output: {p}")
