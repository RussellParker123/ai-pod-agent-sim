import argparse
import logging
import time

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


def run_once(
    etsy_mode: bool = False,
    real: bool = False,
    draft_only: bool = False,
    require_real: bool = False,
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

    listings = []
    failed_real_listings = []
    if real or draft_only:
        from app.marketplace.adapter import get_adapter

        adapter = get_adapter("etsy", draft_only=draft_only)
        for d in designs:
            if d.approved:
                info = adapter.list_design(d, real=real)
                listings.append({"design_id": d.design_id, **info})
                if require_real and info["mode"] != "real":
                    failed_real_listings.append(d.design_id)
                log.info("Listing %s: %s %s (%s)", d.design_id, info["mode"], info["listing_id"], info["status"])
        payload["marketplace_listings"] = listings

    path = save_json(payload, f"run_{timestamp()}.json")
    if require_real:
        if not listings:
            raise RuntimeError("No approved designs were available for real Etsy listings.")
        if failed_real_listings:
            raise RuntimeError(
                "Real Etsy listing failed for design(s): "
                + ", ".join(failed_real_listings)
            )
    return str(path)


def run_until_revenue_goal(
    revenue_goal: float,
    poll_interval: int,
    etsy_mode: bool = False,
) -> str:
    sales_connector = EtsyConnector.from_environment()
    if not sales_connector:
        raise ValueError("Live revenue tracking requires Etsy credentials.")

    total_sales = sales_connector.get_total_sales_usd()
    latest_run = None
    while total_sales < revenue_goal:
        latest_run = run_once(
            etsy_mode=etsy_mode,
            real=True,
            require_real=True,
        )
        total_sales = sales_connector.get_total_sales_usd()
        print(f"Live Etsy sales: ${total_sales:,.2f} / ${revenue_goal:,.2f}")
        if total_sales < revenue_goal:
            time.sleep(poll_interval)

    print(f"Revenue goal reached: ${total_sales:,.2f} / ${revenue_goal:,.2f}")
    return latest_run or ""


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
    parser.add_argument(
        "--revenue-goal",
        type=float,
        help="keep listing approved designs until paid Etsy sales reach this USD amount (requires --real)",
    )
    parser.add_argument(
        "--cycle-delay-seconds",
        type=int,
        default=86400,
        help="seconds between listing batches while pursuing a revenue goal (default: 86400)",
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    if args.revenue_goal is not None and args.revenue_goal <= 0:
        parser.error("--revenue-goal must be greater than zero")
    if args.cycle_delay_seconds <= 0:
        parser.error("--cycle-delay-seconds must be greater than zero")
    if args.revenue_goal is not None and not args.real:
        parser.error("--revenue-goal requires --real")
    if args.revenue_goal is not None and args.draft_only:
        parser.error("--revenue-goal cannot be used with --draft-only")

    real = args.real
    if real and not args.yes:
        kind = (
            "RECURRING ACTIVE"
            if args.revenue_goal is not None
            else "DRAFT" if args.draft_only else "ACTIVE"
        )
        if input(f"Create real {kind} Etsy listings for approved designs? [y/N] ").strip().lower() != "y":
            print("Not confirmed; running in simulation mode.")
            real = False
    if args.revenue_goal is not None and not real:
        print("Revenue goal run cancelled.")
        raise SystemExit(0)
    if args.revenue_goal is not None and real:
        p = run_until_revenue_goal(
            args.revenue_goal,
            args.cycle_delay_seconds,
            etsy_mode=args.etsy_mode,
        )
    else:
        p = run_once(etsy_mode=args.etsy_mode, real=real, draft_only=args.draft_only)
    print(f"Simulation complete. Output: {p}")
