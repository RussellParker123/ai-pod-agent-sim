from app.marketplace.adapter import PRODUCT_TITLES
from app.sim.agents import (
    Design,
    design_agent,
    market_research_agent,
    prompt_agent,
    sweater_hoodie_agent,
)


def test_market_research_uses_shop_tag_signal():
    designs = [
        Design(
            "D001",
            "cozy autumn",
            0.9,
            market_research={
                "source": "shop_active_listing_tags",
                "tag_frequency": 8,
            },
        ),
        Design(
            "D002",
            "bookish humor",
            0.7,
            market_research={
                "source": "shop_active_listing_tags",
                "tag_frequency": 4,
            },
        ),
    ]

    report = market_research_agent(designs)

    assert report["source"] == "shop_active_listing_tags"
    assert [signal["demand_signal"] for signal in report["signals"]] == [1.0, 0.5]
    assert "not marketplace-wide" in report["limitations"]


def test_market_research_simulates_signals_without_shop_data():
    design = Design("D001", "pet lovers", 0.8)

    report = market_research_agent([design])

    assert report["source"] == "simulated"
    assert design.market_research["demand_signal"] == 0.8
    assert "simulated estimates" in report["limitations"]


def test_design_agent_creates_concepts_and_prompts():
    designs = [Design("D001", "coffee culture", 0.8)]

    design_agent(designs)
    prompt_agent(designs)

    assert "original artwork" in designs[0].design_concept
    assert designs[0].design_concept in designs[0].prompt
    assert "no trademark terms" in designs[0].prompt


def test_sweater_hoodie_agent_routes_top_concepts_to_apparel():
    designs = [
        Design(f"D{i:03}", f"niche {i}", 0.5 + i / 10)
        for i in range(4)
    ]

    sweater_hoodie_agent(designs, share=0.5)

    assert designs[3].product_type == "hoodie"
    assert designs[2].product_type == "sweater"
    assert designs[3].unit_cost == 24.0
    assert "front-chest" in designs[3].product_notes
    assert PRODUCT_TITLES["hoodie"] == "Hoodie"
    assert PRODUCT_TITLES["sweater"] == "Sweater"
