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


from app.arena import (  # noqa: E402
    CANVAS_H,
    CANVAS_W,
    COMMAND,
    HUD,
    OPS_BOARD,
    arena_agents,
    facility_layout,
    room_index,
    route,
)


def _rects():
    rooms = station_layout() + facility_layout()
    return [(r["key"], r["x"], r["y"], r["w"], r["h"]) for r in rooms] + [
        ("command", COMMAND["x"], COMMAND["y"], COMMAND["w"], COMMAND["h"]),
        ("ops", OPS_BOARD["x"], OPS_BOARD["y"], OPS_BOARD["w"], OPS_BOARD["h"]),
        ("hud", HUD["x"], HUD["y"], HUD["w"], HUD["h"]),
    ]


def test_rooms_fit_canvas_and_do_not_overlap():
    rects = _rects()
    for key, x, y, w, h in rects:
        assert 0 <= x and x + w <= CANVAS_W and 0 <= y and y + h <= CANVAS_H, key
    for i, a in enumerate(rects):
        for b in rects[i + 1:]:
            overlap = a[1] < b[1] + b[3] and b[1] < a[1] + a[3] and a[2] < b[2] + b[4] and b[2] < a[2] + a[4]
            assert not overlap, (a[0], b[0])


def _crosses(p, q, rect):
    _, x, y, w, h = rect
    if p[0] == q[0]:  # vertical
        return x < p[0] < x + w and max(min(p[1], q[1]), y) < min(max(p[1], q[1]), y + h)
    return y < p[1] < y + h and max(min(p[0], q[0]), x) < min(max(p[0], q[0]), x + w)


def test_routes_are_axis_aligned_and_avoid_other_rooms():
    rooms = room_index()
    keys = list(rooms)
    rects = [r for r in _rects() if r[0] not in ("ops", "hud")]
    for a in keys:
        for b in keys:
            path = route(a, b, rooms)
            assert tuple(path[0]) == tuple(rooms[a]["home"]) and tuple(path[-1]) == tuple(rooms[b]["home"])
            for p, q in zip(path, path[1:]):
                assert p[0] == q[0] or p[1] == q[1], (a, b, p, q)
                for rect in rects:
                    if rect[0] not in (a, b):
                        assert not _crosses(p, q, rect), (a, b, rect[0])


def test_station_routes_match_legacy_find_path_and_unknown_rooms_fail():
    layout = station_layout()
    assert route("trend", "pricing") == [tuple(p) for p in find_path(0, 5, layout)]
    try:
        route("trend", "warp-core")
        assert False
    except KeyError:
        pass


def test_recycling_is_not_the_final_stage():
    html = build_arena_html([])
    assert STATIONS[-1]["key"] == "simulator"
    assert "const FINAL = 'simulator'" in html and "S.length - 1)" not in html
    assert all(f["index"] >= len(STATIONS) for f in facility_layout())


def test_payload_outcomes_and_old_run_defaults():
    df = pd.DataFrame([
        {"design_id": "a", "niche": "n", "compliance_status": "pass", "approved": True, "profit": 3.0,
         "image_uri": "sim://a"},
        {"design_id": "b", "niche": "n", "compliance_status": "flagged", "approved": False, "profit": 0.0,
         "image_uri": "sim://b"},
        {"design_id": "c", "niche": "n", "compliance_status": "pass", "approved": False, "profit": 0.0,
         "image_uri": "sim://c"},
        {"design_id": "d", "niche": "n", "compliance_status": "pass", "approved": False, "profit": 0.0},
    ])
    rec = {"records": [{"record_id": "RC-1", "source_design_id": "b", "status": "quarantined"},
                       {"record_id": "RC-2", "source_design_id": "c", "status": "pending_review"}]}
    rows = {r["id"]: r for r in design_payload(df, recycling=rec)}
    assert rows["a"]["outcome"] == "completed"
    assert rows["b"]["outcome"] == "quarantined" and rows["b"]["recycle_record"] == "RC-1"
    assert rows["c"]["outcome"] == "pending_reuse"
    assert rows["d"]["outcome"] == "held_or_rejected" and rows["d"]["has_image"] is False
    old = design_payload(df[["design_id", "niche", "compliance_status", "approved", "profit"]])
    assert all(r["recycle_status"] is None and r["has_image"] is False for r in old)


def test_agents_placed_by_real_roster_and_transfer_replay():
    team = {"departments": {"prompt": ["prompt-1"], "image": ["image-1", "prompt-2"], "marketing": ["m-1"]},
            "agents": {
                "prompt-1": {"home_department": "prompt", "current_department": "prompt"},
                "prompt-2": {"home_department": "prompt", "current_department": "image"},
                "image-1": {"home_department": "image", "current_department": "image"},
                "m-1": {"home_department": "marketing", "current_department": "marketing"}},
            "events": [{"agent_id": "prompt-2", "from": "prompt", "to": "image", "initiated_by": "auto:demand"}]}
    agents = {a["id"]: a for a in arena_agents(team)}
    assert agents["prompt-2"]["room"] == "prompt"  # start-of-run position; the move is replayed
    assert agents["m-1"]["room"] is None  # marketing has no arena room
    assert agents["recycler-1"]["synthetic"] is True  # placeholder staff are labelled
    html = build_arena_html([], team=team)
    assert '"offsite": ["m-1"]' in html and '"agent_id": "prompt-2"' in html
    defaults = {a["id"] for a in arena_agents(None)}
    assert {"prompt-1", "recycler-1", "trend-scout"} <= defaults


def test_untrusted_text_is_escaped_in_html():
    payload = [{"id": "</script><img src=x onerror=alert(1)>", "niche": "<b>", "flagged": False,
                "approved": True, "profit": 0.0}]
    character = {"display_name": "Dr. Cypher", "line": "</script>&", "visits": [
        {"department": "approval", "purpose": "<i>", "line": "<svg/onload=alert(1)>"}]}
    html = build_arena_html(payload, character=character, run_label="<run>")
    script = html.split("<script>", 1)[1]
    assert script.count("</script>") == 1
    assert "<img" not in script and "<svg" not in script and "\\u003c/script\\u003e" in script
    assert "function esc(" in html and "esc(cy.line)" in html
