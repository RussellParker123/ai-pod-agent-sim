import pandas as pd

from app.arena import STATIONS, build_arena_payload, render_arena_html


def _df():
    return pd.DataFrame([
        {"design_id": "d1", "niche": "cats", "compliance_status": "pass", "approved": True, "profit": 5.0, "revenue": 9.0},
        {"design_id": "d2", "niche": "dogs", "compliance_status": "flagged", "approved": False, "profit": float("nan"), "revenue": float("nan")},
    ])


def test_payload_has_eight_stations_and_designs():
    p = build_arena_payload(_df())
    assert len(STATIONS) == 8 and len(p["stations"]) == 8
    assert p["designs"][1]["flagged"] and p["designs"][1]["profit"] == 0.0


def test_html_escapes_script_close():
    html = render_arena_html(build_arena_payload(_df()), "hi </script><b>")
    assert "</script><b>" not in html
