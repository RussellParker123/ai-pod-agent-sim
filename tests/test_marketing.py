import json
from dataclasses import asdict
from unittest.mock import Mock

from app.marketplace.adapter import EtsyAdapter
from app.sim import run_simulation
from app.sim.agents import Design, to_serializable
from app.sim.marketing import marketing_agent
from app.sim.team import AgentTeam, DEFAULT_WORKERS


def test_marketing_drafts_relevant_copy_without_changing_approval():
    design = Design(
        "D1", "Pet Lovers", 0.8, product_type="mug",
        compliance_status="pass", style_keywords=["retro", "retro"],
    )
    marketing_agent([design])
    draft = design.marketing
    assert draft["primary_keyword"] == "pet lovers mug"
    assert draft["title"] == "Mug - Pet Lovers"
    assert draft["description"] == "Mug featuring pet lovers-themed artwork. Design style: retro."
    assert "retro mug" in draft["tags"]
    assert len(draft["tags"]) == len(set(draft["tags"]))
    assert draft["source"] == "design_metadata"
    assert "ranking guarantees" in draft["limitations"]
    assert not design.approved
    assert to_serializable([design], [])["designs"][0]["marketing"] == draft


def test_long_unicode_keywords_respect_etsy_limits():
    design = Design(
        "D1", "café " * 50, 0.8, compliance_status="pass",
        product_type="tote", style_keywords=["x" * 40] + [f"style{i}" for i in range(20)],
    )
    marketing_agent([design])
    assert len(design.marketing["title"]) <= 140
    assert 0 < len(design.marketing["tags"]) <= 13
    assert all(0 < len(tag) <= 20 for tag in design.marketing["tags"])
    assert "café tote bag" in design.marketing["tags"]


def test_marketing_skips_unsafe_or_incomplete_designs_and_clears_stale_drafts():
    designs = [
        Design("D1", "cats", 0.8, compliance_status="flagged", product_type="mug"),
        Design("D2", "cats", 0.8, product_type="mug"),
        Design("D3", "", 0.8, compliance_status="pass", product_type="mug"),
        Design("D4", "cats", 0.8, compliance_status="pass", product_type="unknown"),
    ]
    for design in designs:
        design.marketing = {"title": "stale"}
    marketing_agent(designs)
    assert all(not design.marketing for design in designs)
    marketing_agent([])


def test_adapter_uses_reviewed_marketing_for_saved_and_in_memory_designs():
    design = Design(
        "D1", "cats", 0.8, compliance_status="pass", product_type="mug", price=19.99,
    )
    marketing_agent([design])
    client = Mock()
    client.create_listing.return_value = {"listing_id": 1, "state": "draft"}
    adapter = EtsyAdapter(client=client, draft_only=True)
    for item in [design, asdict(design)]:
        assert adapter.list_design(item, real=True)["mode"] == "real"
        kwargs = client.create_listing.call_args.kwargs
        assert kwargs["title"] == design.marketing["title"]
        assert kwargs["tags"] == design.marketing["tags"]
        assert kwargs["description"].startswith(design.marketing["description"])
        assert "AI-generated art disclosure" in kwargs["description"]
        assert kwargs["state"] == "draft"
    assert adapter.list_design(asdict(design))["mode"] == "simulated"


def test_adapter_preserves_legacy_saved_run_templates():
    client = Mock()
    client.create_listing.return_value = {"listing_id": 1}
    saved = {"design_id": "D1", "niche": "cats", "product_type": "mug", "price": 19.99}
    adapter = EtsyAdapter(client=client)
    assert adapter.list_design(saved, real=True)["mode"] == "real"
    assert client.create_listing.call_args.kwargs["title"] == "Cats Mug - Original Art"
    assert adapter.list_design({"design_id": "D1"})["listing_id"] == "SIM-D1"


def test_pipeline_records_marketing_and_supports_legacy_teams(tmp_path, monkeypatch):
    monkeypatch.setattr(run_simulation, "DATA_DIR", tmp_path)
    captured = []
    monkeypatch.setattr(
        run_simulation, "save_json",
        lambda payload, name: captured.append(payload) or str(tmp_path / name),
    )
    run_simulation.run_once()
    payload = captured[-1]
    assert any(a["department"] == "marketing" for a in payload["team"]["assignments"])
    for design in payload["designs"]:
        assert bool(design["marketing"]) == (design["compliance_status"] == "pass")
    legacy = AgentTeam(workers={k: v for k, v in DEFAULT_WORKERS.items() if k != "marketing"})
    run_simulation.run_once(team=legacy)
    assert all(not d["marketing"] for d in captured[-1]["designs"])


def test_publish_requires_explicit_review_even_with_marketing(tmp_path, monkeypatch):
    designs = [
        Design("D1", "cats", 0.8, product_type="mug", compliance_status="pass", price=19.99),
        Design("D2", "cats", 0.8, product_type="mug", compliance_status="pass", price=19.99),
        Design("D3", "cats", 0.8, product_type="mug", compliance_status="flagged", price=19.99),
    ]
    marketing_agent(designs)
    payload = to_serializable(designs, [])
    payload["manager"] = {"design_scores": {
        d.design_id: {"manager_decision": "GREENLIGHT"} for d in designs
    }}
    run_name = "run_marketing.json"
    (tmp_path / run_name).write_text(json.dumps(payload))
    (tmp_path / "overrides.json").write_text(json.dumps({
        run_name: {"D1": "approve", "D3": "force_approve"}
    }))
    monkeypatch.setattr(run_simulation, "DATA_DIR", tmp_path)
    client = Mock()
    client.create_listing.return_value = {"listing_id": 1}
    monkeypatch.setattr(
        "app.marketplace.adapter.get_adapter",
        lambda *args, **kwargs: EtsyAdapter(client=client),
    )
    run_simulation.publish_reviewed_run(run_name, real=True)
    client.create_listing.assert_called_once()
    assert client.create_listing.call_args.kwargs["title"] == designs[0].marketing["title"]
    result = json.loads((tmp_path / f"published_{run_name}").read_text())
    assert result["review_status"]["D2"] == "PENDING_REVIEW"
    assert result["review_status"]["D3"] == "BLOCKED"
