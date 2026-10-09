"""Offline simulation launch (CLI/in-app) and the dashboard's no-run, launch
and legacy-run paths. No network, no paid APIs, no publishing."""
import json

import pytest

from app.sim import run_simulation

pytest.importorskip("streamlit.testing.v1")
from streamlit.testing.v1 import AppTest  # noqa: E402

DASHBOARD = "app/dashboard.py"


def test_run_once_batch_size_seed_and_unique_names(offline_data_dir, monkeypatch):
    monkeypatch.setattr(run_simulation, "timestamp", lambda: "20260101_000000")
    first = run_simulation.run_once(batch_size=8, seed=7)
    second = run_simulation.run_once(batch_size=8, seed=7)
    assert first.endswith("run_20260101_000000.json") and second.endswith("run_20260101_000000_2.json")
    a, b = (json.loads(open(p, encoding="utf-8").read()) for p in (first, second))
    assert len(a["designs"]) + len(a["recycling"]["skipped_no_image"]) == 8
    assert [d["niche"] for d in a["designs"]] == [d["niche"] for d in b["designs"]]  # seeded
    themed = json.loads(open(run_simulation.run_once(batch_size=8, seed=7, theme_request="Western"),
                             encoding="utf-8").read())
    assert themed["theme_request"] == "Western" and themed["resolved_theme"] == "western desert"
    assert themed["designs"] and {d["niche"] for d in themed["designs"]} == {"western desert"}
    for record in a["recycling"]["records"]:
        analysis = record["analysis"]
        assert analysis is None or (analysis["image_inspected"] is False and "suggestions" in analysis)
    assert "marketplace_listings" not in a  # never published
    with pytest.raises(ValueError):
        run_simulation.run_once(batch_size=0)


def test_cli_accepts_batch_size_and_seed():
    args = run_simulation.build_arg_parser().parse_args(
        ["--batch-size", "6", "--seed", "3", "--theme", "fall"]
    )
    assert args.batch_size == 6 and args.seed == 3 and args.theme == "fall" and not args.real


@pytest.mark.parametrize(("request", "expected"), [
    ("western", ["western desert"]),
    ("Fall", ["cozy autumn"]),
    ("a cozy autumn harvest", ["cozy autumn"]),
    ("celestial cats", ["celestial cats"]),
    ("", run_simulation.DEFAULT_NICHES),
])
def test_theme_request_selects_matching_niche(request, expected):
    assert run_simulation._niches_for_theme(request, run_simulation.DEFAULT_NICHES) == expected


def test_dashboard_without_runs_offers_offline_launch_and_writes_nothing(offline_data_dir):
    at = AppTest.from_file(DASHBOARD, default_timeout=60).run()
    assert not at.exception
    assert any("NO SIMULATION RUNS YET" in w.value for w in at.warning)
    assert [b.label for b in at.button] == ["Run offline simulation"]
    at.run()  # plain reruns must not write anything
    assert list(offline_data_dir.iterdir()) == []


def test_dashboard_launch_creates_and_selects_new_run(offline_data_dir):
    at = AppTest.from_file(DASHBOARD, default_timeout=90).run()
    at.text_input[0].set_value("western")
    at.number_input[0].set_value(6)
    at.checkbox[0].check()
    at.button[0].click().run()
    assert not at.exception and not at.error
    runs = sorted(offline_data_dir.glob("run_*.json"))
    assert len(runs) == 1
    payload = json.loads(runs[0].read_text(encoding="utf-8"))
    assert payload["theme_request"] == "western" and payload["resolved_theme"] == "western desert"
    assert {d["niche"] for d in payload["designs"]} == {"western desert"}
    assert at.sidebar.selectbox[0].value == runs[0].name
    assert any("saved and selected" in s.value for s in at.success)
    assert at.get("iframe"), "arena iframe should render for the new run"


def test_dashboard_launch_failure_is_reported(offline_data_dir, monkeypatch):
    def boom(**kwargs):
        raise RuntimeError("disk full")

    monkeypatch.setattr(run_simulation, "run_once", boom)
    at = AppTest.from_file(DASHBOARD, default_timeout=60).run()
    at.button[0].click().run()
    assert not at.exception
    assert any("disk full" in e.value for e in at.error)
    assert not list(offline_data_dir.glob("run_*.json"))


@pytest.mark.parametrize("payload", [
    # Older run: no team, recycling, character, results or image URIs.
    {"designs": [{"design_id": "D1", "niche": "cats", "compliance_status": "pass", "approved": True},
                 {"design_id": "D2", "niche": "dogs", "compliance_status": "flagged", "approved": False}],
     "manager": {"decisions": [{"stage": "trend", "action": "keep"}, {"stage": "approval", "action": "greenlight"}]}},
    # Reject-all run.
    {"designs": [{"design_id": f"D{i}", "niche": "n", "compliance_status": "flagged", "approved": False,
                  "image_uri": f"sim://images/D{i}.png"} for i in range(3)], "results": []},
])
def test_dashboard_renders_legacy_and_reject_all_runs(offline_data_dir, payload):
    (offline_data_dir / "run_20200101_000000.json").write_text(json.dumps(payload), encoding="utf-8")
    at = AppTest.from_file(DASHBOARD, default_timeout=60).run()
    assert not at.exception
    assert at.get("iframe")
    assert [p.name for p in offline_data_dir.iterdir()] == ["run_20200101_000000.json"]  # untouched
