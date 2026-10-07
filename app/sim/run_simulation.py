from app.sim.agents import (
    trend_agent,
    prompt_agent,
    image_agent,
    compliance_agent,
    mockup_agent,
    pricing_agent,
    approval_gate,
    listing_simulator,
    to_serializable,
)
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

    designs = trend_agent(niches=niches, k=24)
    prompt_agent(designs)
    image_agent(designs)
    compliance_agent(designs)
    mockup_agent(designs)
    pricing_agent(designs, target_margin=0.42)
    approval_gate(designs, auto_approve_safe=True)

    results = listing_simulator(designs)
    payload = to_serializable(designs, results)

    fname = f"run_{timestamp()}.json"
    path = save_json(payload, fname)
    return str(path)


if __name__ == "__main__":
    p = run_once()
    print(f"Simulation complete. Output: {p}")
