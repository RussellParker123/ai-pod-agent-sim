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

    monkeypatch.setattr("app.marketplace.adapter.get_adapter", lambda **kwargs: Adapter())
    result_path = run_simulation.publish_reviewed_run(run_name)

    assert listed == ["D1", "D2"]
    assert run_path.read_text(encoding="utf-8") == json.dumps(payload)
    published = json.loads((tmp_path / result_path.split("/")[-1]).read_text(encoding="utf-8"))
    assert published["review_status"]["D3"] == "BLOCKED"
    assert [item["design_id"] for item in published["marketplace_listings"]] == ["D1", "D2"]
