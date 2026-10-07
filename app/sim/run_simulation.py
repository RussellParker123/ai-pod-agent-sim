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


def run_once(etsy_mode: bool = False) -> str:
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

    path = save_json(payload, f"run_{timestamp()}.json")
    return str(path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the AI POD agent simulation.")
    parser.add_argument(
        "--etsy-mode",
        action="store_true",
        help="Use read-only Etsy store data when credentials are configured.",
    )
    args = parser.parse_args()
    p = run_once(etsy_mode=args.etsy_mode)
    print(f"Simulation complete. Output: {p}")
