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
from app.sim.utils import save_json, timestamp


def run_once() -> str:
    niches = [
        "cozy autumn",
        "pet lovers",
        "minimalist motivation",
        "retro outdoors",
        "bookish humor",
        "coffee culture",
    ]
    manager = ManagerAgent()

    designs = trend_agent(niches=niches, k=24)
    designs = manager.review_trends(designs)

    prompt_agent(designs)
    image_agent(designs)
    compliance_agent(designs)
    manager.review_compliance(designs, recheck=compliance_agent)

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
    p = run_once()
    print(f"Simulation complete. Output: {p}")
