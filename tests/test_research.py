from app.sim.agents import Design, prompt_agent
from app.sim.research import apply_research, research_agent


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
