from app.sim.agents import Design, pricing_agent, prompt_agent
from app.sim.research import apply_research, pricing_research_agent, research_agent


class FakeConnector:
    def get_best_sellers(self, limit=10):
        return [
            {"title": "Retro outdoors mug", "tags": ["retro outdoors"], "demand": 100},
            {"title": "Pet lovers tshirt", "tags": ["pet lovers"], "demand": 10},
        ]


def test_research_ranks_and_briefs_departments():
    niches = ["retro outdoors", "pet lovers"]
    r = research_agent(niches, etsy_connector=FakeConnector())
    assert r["source"] == "etsy"
    assert list(r["top_niches"])[0] == "retro outdoors"
    assert r["top_product_types"][0] == "mug"
    d = [Design("D1", "retro outdoors", 0.5)]
    apply_research(d, r)
    prompt_agent(d)
    assert d[0].trend_score > 0.5
    assert "retro" in d[0].prompt


def test_research_falls_back_to_simulation():
    r = research_agent(["pet lovers"])
    assert r["source"] == "simulated" and r["best_sellers"]


def test_pricing_research_uses_median_usd_shop_prices_by_product():
    class InventoryConnector:
        def get_inventory(self):
            return [
                {"title": "Coffee mug", "price": 12, "currency_code": "USD"},
                {"title": "Travel mug", "price": 18, "currency_code": "USD"},
                {"title": "Mug", "price": 100, "currency_code": "EUR"},
                {"title": "Tote bag", "price": 20, "currency_code": "USD"},
            ]

    research = pricing_research_agent(InventoryConnector())

    assert research["source"] == "etsy_shop_inventory"
    assert research["benchmarks"] == {
        "mug": {"median_price": 15.0, "listing_count": 2},
        "tote": {"median_price": 20.0, "listing_count": 1},
    }


def test_pricing_agent_uses_market_reference_without_undercutting_margin():
    designs = [
        Design("D1", "coffee culture", 0.8, product_type="mug", unit_cost=6.5),
        Design("D2", "coffee culture", 0.8, product_type="mug", unit_cost=6.5),
    ]

    pricing_agent(designs, target_margin=0.4, market_prices={"mug": 12})

    assert designs[0].price == 12
    assert designs[1].price == 10.84
    assert all((d.price - d.unit_cost) / d.price >= 0.4 for d in designs)
