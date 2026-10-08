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


from app.arena import design_route, recycling_plans, stage_assignments  # noqa: E402
from app.sim.characters import character_from_report  # noqa: E402


def _config(html):
    import json

    return json.loads(html.split("const CFG = ", 1)[1].split(";\n", 1)[0])


def test_design_routes_cover_every_outcome():
    assert design_route(False, True, False) == (
        ["trend", "prompt", "image", "compliance", "mockup", "pricing", "approval", "simulator"], "completed")
    assert design_route(True, False, False) == (["trend", "prompt", "image", "compliance"], "rejected")
    assert design_route(True, False, True, recycle_outcome="quarantined")[0][-1] == "recycling"
    assert design_route(False, False, False, "HOLD")[1] == "held"
    assert design_route(False, False, False, "BLOCK")[1] == "blocked"
    assert design_route(False, False, False)[1] == "held"  # older runs: no recorded decision
    path, res = design_route(False, False, True, "BLOCK", "pending_reuse")
    assert path[-2:] == ["approval", "recycling"] and res == "pending_reuse"


def test_reject_all_run_expects_no_work_downstream():
    rows = [{"id": f"D{i}", "niche": "n", "flagged": True, "approved": False, "profit": 0.0} for i in range(3)]
    cfg = _config(build_arena_html(rows))
    assert cfg["expected"] == {"trend": 3, "prompt": 3, "image": 3, "compliance": 3}
    assert all(d["resolution"] == "rejected" for d in cfg["designs"])
    assert _config(build_arena_html([]))["expected"] == {}


def test_stage_assignments_follow_recorded_round_robin():
    ids = ["D1", "D2", "D3", "D4-R1-abcd"]
    team = {"assignments": [
        {"department": "prompt", "worker_id": "prompt-1", "design_count": 2},
        {"department": "prompt", "worker_id": "prompt-2", "design_count": 1},
        {"department": "compliance", "worker_id": "compliance-1", "design_count": 2},
        {"department": "compliance", "worker_id": "compliance-2", "design_count": 2},
        {"department": "image", "worker_id": "image-1", "design_count": 9},  # inconsistent: not guessed
    ]}
    out = stage_assignments(ids, {"D4-R1-abcd"}, team)
    assert out["D1"]["prompt"] == "prompt-1" and out["D2"]["prompt"] == "prompt-2" and out["D3"]["prompt"] == "prompt-1"
    assert "prompt" not in out["D4-R1-abcd"]  # recycled candidates skip prompt/image
    assert [out[i]["compliance"] for i in ids] == ["compliance-1", "compliance-2", "compliance-1", "compliance-2"]
    assert all("image" not in v for v in out.values())
    assert stage_assignments(ids, set(), None) == {}


def test_payload_uses_recorded_team_and_manager_decisions():
    df = pd.DataFrame([
        {"design_id": "a", "niche": "n", "compliance_status": "pass", "approved": False, "profit": 0.0},
        {"design_id": "b", "niche": "n", "compliance_status": "pass", "approved": False, "profit": 0.0},
    ])
    team = {"assignments": [{"department": "mockup", "worker_id": "mockup-2", "design_count": 2}]}
    manager = {"design_scores": {"a": {"manager_decision": "BLOCK"}, "b": {"manager_decision": "HOLD"}}}
    rows = {r["id"]: r for r in design_payload(df, team=team, manager=manager)}
    assert rows["a"]["resolution"] == "blocked" and rows["b"]["resolution"] == "held"
    assert rows["a"]["assigned"] == {"mockup": "mockup-2"}


def _store_record(record_id, run, reason="low fit", analysis=True):
    rec = {"record_id": record_id, "source_ref": run, "source_design_id": "D1", "status": "pending_review",
           "image_uri": "sim://images/D1.png", "rejection": {"by": "manager", "reason": reason, "stage": "approval"},
           "original": {"niche": "cozy autumn", "product_type": "tote"}, "analysis": None}
    if analysis:
        rec["analysis"] = {"recycler_id": "recycler-1", "method": "metadata_cross_reference", "image_inspected": False,
                           "quarantine": False, "limitations": "metadata only",
                           "suggestions": [{"suggestion_id": "S-1", "type": "alternate_product",
                                            "target_niche": "cozy autumn", "target_product": "mug",
                                            "confidence": 0.71, "reasons": ["fit 0.9"], "references": ["product_fit:x"]}]}
    return rec


def test_recycling_plans_only_attribute_this_runs_records():
    run = "run_1.json"
    payload = {"records": [{"record_id": "RC-a", "source_design_id": "D1", "status": "pending_review"},
                           {"record_id": "RC-b", "source_design_id": "D2", "status": "pending_analysis"},
                           {"record_id": "RC-a", "source_design_id": "D1", "status": "pending_review"}]}
    store = [_store_record("RC-a", run), _store_record("RC-b", run, analysis=False),
             _store_record("RC-x", "run_other.json")]
    out = recycling_plans(payload, store, run)
    assert set(out["plans"]) == {"RC-a", "RC-b"} and out["other_queue_records"] == 1
    a = out["plans"]["RC-a"]
    assert a["analysis"]["suggestions"][0]["target_product"] == "mug"
    assert a["analysis"]["image_inspected"] is False and a["analysis_source"] == "recycling queue (current)"
    assert "no image pixels" in a["pixels"] and a["reason"] == "low fit"
    assert out["plans"]["RC-b"]["analysis"] is None  # shown as "not analyzed yet", never invented
    # Older payload + no queue file: falls back to the run snapshot or None.
    snap = {"records": [{"record_id": "RC-s", "source_design_id": "D9", "status": "pending_review",
                         "analysis": {"recycler_id": "recycler-1", "suggestions": []}}]}
    plan = recycling_plans(snap, [], run)["plans"]["RC-s"]
    assert plan["analysis_source"] == "run snapshot" and plan["current_status"] is None
    assert recycling_plans(None, None, run) == {"plans": {}, "other_queue_records": 0}


def test_recycler_plan_text_is_escaped_in_html():
    evil = "</script><img src=x onerror=alert(1)>"
    plans = recycling_plans({"records": [{"record_id": "RC-a", "source_design_id": "D1", "status": "x"}]},
                            [_store_record("RC-a", "r", reason=evil)], "r")
    rows = [{"id": "D1", "niche": "n", "flagged": False, "approved": False, "profit": 0.0, "recycle_record": "RC-a",
             "recycle_status": "pending_review"}]
    html = build_arena_html(rows, plans=plans)
    script = html.split("<script>", 1)[1]
    assert script.count("</script>") == 1 and "<img" not in script
    assert _config(html)["plans"]["RC-a"]["reason"] == evil
    assert "esc(p.reason)" in html


def test_cypher_basis_and_reconstructed_visits():
    old = character_from_report({"decisions": [{"stage": "trend", "action": "keep"},
                                               {"stage": "approval", "action": "hold"}]})
    cfg = _config(build_arena_html([], character=old.to_dict()))
    assert cfg["cypher"]["basis"] == "reconstructed"
    assert {v["source"] for v in cfg["cypher"]["visits"]} == {"reconstructed"}
    assert _config(build_arena_html([], character=character_from_report(None).to_dict()))["cypher"]["basis"] == "none"
    recorded = {"display_name": "Dr. Cypher", "visits": [{"department": "trend", "purpose": "p", "line": "l"}]}
    assert _config(build_arena_html([], character=recorded))["cypher"]["basis"] == "recorded"


def test_unstaffed_rooms_get_labelled_placeholders():
    team = {"departments": {"prompt": ["p-1"], "compliance": ["c-1"]}}
    agents = {a["id"]: a for a in arena_agents(team)}
    for room in ("image", "mockup", "pricing"):
        assert agents[f"{room}-placeholder"]["synthetic"] is True and agents[f"{room}-placeholder"]["room"] == room
    assert agents["p-1"]["synthetic"] is False and "prompt-placeholder" not in agents
