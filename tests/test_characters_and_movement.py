import json

import pytest

from app.sim import run_simulation
from app.sim.characters import CHARACTER_ID, DrCypher, character_from_report
from app.sim.manager import ManagerAgent
from app.sim.team import (
    AgentTeam,
    TransferError,
    agents_for,
    load_team_state,
    save_team_state,
)


def test_dr_cypher_identity_is_stable_and_serializable():
    cypher = DrCypher()
    cypher.visit("compliance", "Reviewing flags", ["D1"], rework=1, reject=0)
    data = json.loads(json.dumps(cypher.to_dict()))
    data["character_id"] = "impostor"
    data["display_name"] = "<script>alert(1)</script>"
    restored = DrCypher.from_dict(data)
    assert restored.character_id == CHARACTER_ID and restored.display_name == "Dr. Cypher"
    assert restored.location == "compliance" and restored.visits[0]["counts"] == {"rework": 1, "reject": 0}


def test_dr_cypher_status_follows_manager_decisions():
    manager = ManagerAgent()
    manager.review_compliance([], recheck=lambda items: None)
    manager.batch = {}
    manager.character.react({"status": "NO-GO", "flag_rate": 0.5})
    assert manager.character.mood == "exasperated"
    report = {"manager_id": "manager-1", "decisions": [], "character": manager.character.to_dict()}
    assert character_from_report(report).visits[0]["department"] == "compliance"


def test_old_runs_reconstruct_dr_cypher_from_decisions():
    old = {"manager_id": "m", "batch": {"status": "GO", "flag_rate": 0.0},
           "decisions": [{"stage": "trend", "action": "drop"}, {"stage": "approval", "action": "greenlight"}]}
    cypher = character_from_report(old)
    assert [v["department"] for v in cypher.visits] == ["trend", "approval"]
    assert cypher.mood == "elated" and cypher.location == "command"
    assert character_from_report(None).character_id == CHARACTER_ID


def test_transfer_changes_subsequent_assignments_and_records_event():
    team = AgentTeam()
    seen = []
    team.run_stage("image", list(range(4)), lambda items, worker_id: seen.append(worker_id), worker_kwarg="worker_id")
    assert set(seen) == {"image-1", "image-2"}

    event = team.transfer("prompt-2", "image", reason="art backlog")
    assert event["from"] == "prompt" and event["to"] == "image"
    seen.clear()
    team.run_stage("image", list(range(6)), lambda items, worker_id: seen.append(worker_id), worker_kwarg="worker_id")
    assert set(seen) == {"image-1", "image-2", "prompt-2"}
    assert "prompt-2" not in team.workers["prompt"]
    agent = team.report()["agents"]["prompt-2"]
    assert agent["home_department"] == "prompt" and agent["current_department"] == "image"
    assert team.report()["events"][0]["agent_id"] == "prompt-2"
    assignment = [a for a in team.assignments if a["worker_id"] == "prompt-2"][0]
    assert assignment["department"] == "image" and assignment["home_department"] == "prompt"


@pytest.mark.parametrize("agent_id, destination, message", [
    ("prompt-1", "warp-core", "Unknown department"),
    ("ghost-7", "image", "Unknown agent"),
    ("prompt-1", "pricing", "not trained"),
    ("prompt-1", "prompt", "already in"),
    ("recycler-1", "compliance", "must keep at least"),
])
def test_invalid_transfers_are_rejected(agent_id, destination, message):
    team = AgentTeam()
    with pytest.raises(TransferError, match=message):
        team.transfer(agent_id, destination)
    assert team.events == []


def test_busy_agent_cannot_move_mid_task():
    team = AgentTeam()
    errors = []

    def work(items):
        try:
            team.transfer("image-1", "prompt")
        except TransferError as exc:
            errors.append(str(exc))

    team.run_stage("image", [1, 2], work)
    assert errors and "mid-task" in errors[0]
    assert team.agents["image-1"]["status"] == "idle"


def test_duplicate_worker_ids_across_departments_rejected():
    with pytest.raises(ValueError, match="appears in both"):
        AgentTeam(workers={"prompt": ["w1"], "image": ["w1"]})


def test_custom_teams_remain_compatible():
    team = AgentTeam(workers={"prompt": ["a", "b"]}, manager_id="boss")
    team.run_stage("prompt", [1, 2, 3], lambda items: None)
    report = team.report()
    assert report["manager_id"] == "boss" and report["departments"] == {"prompt": ["a", "b"]}
    assert [a["design_count"] for a in report["assignments"]] == [2, 1]
    # legacy report without agents/events
    legacy = agents_for({"departments": {"prompt": ["a"]}})
    assert legacy["a"]["current_department"] == "prompt"


def test_demand_rebalance_is_temporary_and_released():
    team = AgentTeam()
    moves = team.rebalance({"recycling": 9}, max_load=4)
    assert moves and all(m["initiated_by"] == "auto:demand" and m["to"] == "recycling" for m in moves)
    assert len(team.workers["compliance"]) >= 1
    back = team.release_temporary()
    assert [m["to"] for m in back] == ["compliance"] * len(moves)
    assert team.workers["recycling"] == ["recycler-1"]


def test_roster_persists_and_drives_next_simulation_run(tmp_path, monkeypatch):
    team = AgentTeam()
    team.transfer("pricing-2", "marketing", reason="launch week")
    save_team_state(team, tmp_path / "team_state.json")
    loaded = load_team_state(tmp_path / "team_state.json")
    assert loaded.agents["pricing-2"]["current_department"] == "marketing"
    assert loaded.agents["pricing-2"]["home_department"] == "pricing"
    assert loaded.agents["pricing-2"]["history"][0]["reason"] == "launch week"

    monkeypatch.setattr(run_simulation, "DATA_DIR", tmp_path)
    monkeypatch.setattr(run_simulation.EtsyConnector, "from_environment", lambda: None)
    captured = []
    monkeypatch.setattr(run_simulation, "save_json", lambda payload, name: captured.append(payload) or name)
    run_simulation.run_once()
    marketing_workers = {a["worker_id"] for a in captured[0]["team"]["assignments"] if a["department"] == "marketing"}
    assert "pricing-2" in marketing_workers
    assert captured[0]["manager"]["character"]["character_id"] == CHARACTER_ID


def test_invalid_or_old_team_state_falls_back(tmp_path):
    bad = tmp_path / "team_state.json"
    bad.write_text("{not json")
    assert load_team_state(bad).workers["recycling"] == ["recycler-1"]
    old = tmp_path / "old.json"
    old.write_text(json.dumps({"departments": {"prompt": ["prompt-1"], "image": ["image-1"]}}))
    team = load_team_state(old)
    assert team.workers["prompt"] == ["prompt-1"] and "recycling" in team.workers
