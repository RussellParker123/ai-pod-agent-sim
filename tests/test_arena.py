import pandas as pd

from app.arena import STATIONS, build_arena_html, design_payload, find_path, station_layout


def test_eight_stations_with_unique_rooms():
    layout = station_layout()
    assert len(STATIONS) == 8 and len(layout) == 8
    assert len({(s["x"], s["y"]) for s in layout}) == 8


def test_pathfinding_goes_through_corridor():
    layout = station_layout()
    path = find_path(0, 5, layout)
    assert path[0] == layout[0]["home"] and path[-1] == layout[5]["home"]
    assert path[1][1] == path[2][1]  # both doors on corridor


def test_build_html_embeds_designs():
    df = pd.DataFrame([{"design_id": "d1", "niche": "cats", "compliance_status": "flagged",
                        "approved": False, "profit": float("nan")}])
    payload = design_payload(df)
    assert payload[0]["flagged"] is True and payload[0]["profit"] == 0.0
    assert '"d1"' in build_arena_html(payload)
