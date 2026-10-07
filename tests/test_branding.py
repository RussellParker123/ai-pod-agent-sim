from app.sim.branding import branding_agent


def test_branding_has_all_parts():
    b = branding_agent(["pet lovers", "coffee culture"], seed=1)
    assert len(b["shop_name"]["suggestions"]) == 5
    assert all(4 <= len(n) <= 20 and n.isalnum() for n in b["shop_name"]["etsy_safe"])
    assert b["logo"]["prompt"] and b["banner"]["prompt"] and b["story"]
