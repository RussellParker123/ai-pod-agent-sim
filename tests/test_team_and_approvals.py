import json

from app.sim.agents import Design
from app.sim.approvals import final_review_status
from app.sim.team import AgentTeam
from app.sim import run_simulation


def test_team_distributes_designs_across_workers():
    team = AgentTeam(workers={"prompt": ["prompt-a", "prompt-b"]})
    designs = [Design(f"D{i}", "cats", 0.8) for i in range(5)]
    processed = []

    team.run_stage("prompt", designs, lambda items: processed.extend(d.design_id for d in items))

    assert set(processed) == {d.design_id for d in designs}
    counts = [assignment["design_count"] for assignment in team.assignments]
    assert counts == [3, 2]
    assert team.report()["manager_id"] == "manager-1"


def test_team_rejects_duplicate_worker_ids():
    try:
        AgentTeam(workers={"prompt": ["worker", "worker"]})
        assert False, "Expected duplicate worker IDs to fail"
    except ValueError:
        pass


def test_review_status_requires_explicit_approval_and_respects_compliance():
    assert final_review_status("GREENLIGHT", "pass", "none") == "PENDING_REVIEW"
    assert final_review_status("GREENLIGHT", "pass", "approve") == "APPROVED"
    assert final_review_status("HOLD", "pass", "force_approve") == "FORCE_APPROVED"
    assert final_review_status("HOLD", "flagged", "force_approve") == "BLOCKED"


def test_publish_reviewed_run_only_lists_approved_designs(tmp_path, monkeypatch):
    run_name = "run_example.json"
    run_path = tmp_path / run_name
    payload = {
        "designs": [
            {"design_id": "D1", "compliance_status": "pass"},
            {"design_id": "D2", "compliance_status": "pass"},
            {"design_id": "D3", "compliance_status": "flagged"},
        ],
        "manager": {
            "design_scores": {
                "D1": {"manager_decision": "GREENLIGHT"},
                "D2": {"manager_decision": "HOLD"},
                "D3": {"manager_decision": "HOLD"},
            }
        },
    }
    run_path.write_text(json.dumps(payload), encoding="utf-8")
    (tmp_path / "overrides.json").write_text(
        json.dumps(
            {
                run_name: {
                    "D1": "approve",
                    "D2": "force_approve",
                    "D3": "force_approve",
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(run_simulation, "DATA_DIR", tmp_path)
    listed = []

    class Adapter:
        def list_design(self, design, real=False):
            listed.append(design["design_id"])
            return {"mode": "simulated"}

    monkeypatch.setattr("app.marketplace.adapter.get_adapter", lambda *args, **kwargs: Adapter())
    result_path = run_simulation.publish_reviewed_run(run_name)

    assert listed == ["D1", "D2"]
    assert run_path.read_text(encoding="utf-8") == json.dumps(payload)
    published = json.loads((tmp_path / result_path.split("/")[-1]).read_text(encoding="utf-8"))
    assert published["review_status"]["D3"] == "BLOCKED"
    assert [item["design_id"] for item in published["marketplace_listings"]] == ["D1", "D2"]


def test_etsy_config_survives_team_pipeline(tmp_path, monkeypatch):
    config = {
        "niches": ["coffee culture"],
        "product_types": ["tote"],
        "target_margin": 0.5,
        "fees": {"listing_fee": 0.2},
    }
    config_path = tmp_path / "etsy_config.json"
    config_path.write_text(json.dumps(config))
    monkeypatch.setattr(run_simulation, "ETSY_CONFIG_PATH", config_path)
    monkeypatch.setattr(run_simulation, "DATA_DIR", tmp_path)
    monkeypatch.setattr(run_simulation.EtsyConnector, "from_environment", lambda: None)
    captured = []
    monkeypatch.setattr(
        run_simulation, "save_json",
        lambda payload, name: captured.append(payload) or str(tmp_path / name),
    )
    fees_applied = []
    apply_fees = run_simulation.apply_etsy_fees

    def record_fees(designs, results, fees):
        fees_applied.append(fees)
        apply_fees(designs, results, fees)

    monkeypatch.setattr(run_simulation, "apply_etsy_fees", record_fees)
    run_simulation.run_once(etsy_mode=True)
    payload = captured[0]
    assert payload["etsy_config"] == config
    assert fees_applied == [config["fees"]]
    assert payload["team"]["assignments"]
    assert payload["designs"]
    assert all(d["product_type"] == "tote" for d in payload["designs"])
    assert all((d["price"] - d["unit_cost"]) / d["price"] >= 0.5 for d in payload["designs"])


def test_etsy_mode_without_config_keeps_mock_fallback(tmp_path, monkeypatch):
    monkeypatch.setattr(run_simulation, "ETSY_CONFIG_PATH", tmp_path / "missing.json")
    monkeypatch.setattr(run_simulation, "DATA_DIR", tmp_path)
    monkeypatch.setattr(run_simulation.EtsyConnector, "from_environment", lambda: None)
    captured = []
    monkeypatch.setattr(
        run_simulation, "save_json",
        lambda payload, name: captured.append(payload) or str(tmp_path / name),
    )
    run_simulation.run_once(etsy_mode=True)
    assert captured[0]["etsy_mode"]
    assert captured[0]["etsy_config"] is None
    assert captured[0]["research"]["source"] == "simulated"
