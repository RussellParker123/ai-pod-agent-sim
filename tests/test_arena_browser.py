"""Executes the arena's JavaScript in a real headless browser.

Requires Playwright plus a Chromium (``pip install playwright && playwright
install chromium``; a system chromium/chrome is used as a fallback). Skipped
when neither is available."""
import shutil

import pandas as pd
import pytest

from app.arena import build_arena_html, design_payload, recycling_plans
from app.sim.characters import character_from_report

sync_api = pytest.importorskip("playwright.sync_api")


@pytest.fixture(scope="module")
def browser():
    with sync_api.sync_playwright() as p:
        try:
            b = p.chromium.launch()
        except Exception:  # noqa: BLE001 - bundled browser not installed
            exe = next((shutil.which(n) for n in ("chromium", "chromium-browser", "google-chrome")
                        if shutil.which(n)), None)
            if not exe:
                pytest.skip("no Chromium available for browser tests")
            b = p.chromium.launch(executable_path=exe)
        yield b
        b.close()


def open_arena(browser, html, tmp_path, width=1000):
    path = tmp_path / "arena.html"
    path.write_text(html, encoding="utf-8")
    page = browser.new_page(viewport={"width": width, "height": 1100})
    errors = []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(path.as_uri())
    page.wait_for_function("() => window.arenaDebug !== undefined")
    page.click("#play")  # pause the real-time loop; tests advance the same update() deterministically
    return page, errors


def run_until_finished(page, limit=600):
    for _ in range(limit // 10):
        page.evaluate("() => arenaDebug.advance(10)")
        s = page.evaluate("() => arenaDebug.summary()")
        if s["finished"] and s["cypher"]["home"]:
            return s
    return page.evaluate("() => arenaDebug.summary()")


RUN = "run_20260101_000000.json"


def _rich_run():
    """A new-style run: recorded assignments, demand/end-of-shift transfers,
    manager decisions and three recycling records (planned, quarantined,
    not analysed)."""
    rows = []
    for i in range(1, 9):
        rows.append({"design_id": f"D{i}", "niche": "cozy autumn", "compliance_status": "pass", "approved": i <= 4,
                     "profit": 5.0 * i, "image_uri": f"sim://images/D{i}.png"})
    rows[4]["compliance_status"] = "flagged"   # D5 -> quarantined via recycling
    df = pd.DataFrame(rows)
    team = {
        "departments": {"prompt": ["prompt-1", "prompt-2"], "image": ["image-1", "image-2"],
                        "compliance": ["compliance-1"], "mockup": ["mockup-1", "mockup-2"],
                        "pricing": ["pricing-1", "pricing-2"], "recycling": ["recycler-1"]},
        "agents": {
            **{a: {"home_department": d, "current_department": d} for d, ids in {
                "prompt": ["prompt-1", "prompt-2"], "image": ["image-1", "image-2"], "compliance": ["compliance-1"],
                "mockup": ["mockup-1", "mockup-2"], "pricing": ["pricing-1", "pricing-2"],
                "recycling": ["recycler-1"]}.items() for a in ids},
            "compliance-2": {"home_department": "compliance", "current_department": "compliance"},
        },
        "assignments": [{"department": d, "worker_id": f"{d}-{k}", "design_count": 4}
                        for d in ("prompt", "image", "mockup", "pricing") for k in (1, 2)]
        + [{"department": "compliance", "worker_id": "compliance-1", "design_count": 4},
           {"department": "compliance", "worker_id": "compliance-2", "design_count": 4}],
        "events": [
            {"agent_id": "compliance-2", "from": "compliance", "to": "recycling", "initiated_by": "auto:demand",
             "reason": "demand"},
            {"agent_id": "compliance-2", "from": "recycling", "to": "compliance", "initiated_by": "auto:end_of_shift",
             "reason": "temporary assignment finished"},
        ],
    }
    manager = {"design_scores": {"D6": {"manager_decision": "HOLD"}, "D7": {"manager_decision": "BLOCK"},
                                 "D8": {"manager_decision": "BLOCK"}},
               "character": {"display_name": "Dr. Cypher", "mood": "skeptical", "line": "Report filed.", "visits": [
                   {"department": "trend", "purpose": "Reviewing trend picks", "line": "Kept 8."},
                   {"department": "compliance", "purpose": "Reviewing compliance flags", "line": "1 rejected."},
                   {"department": "pricing", "purpose": "Checking margins", "line": "Repriced 0."},
                   {"department": "approval", "purpose": "Scoring", "line": "Greenlight 4, hold 1, block 2."},
                   {"department": "recycling", "purpose": "Delivering rejected art", "line": "3 delivered."}]}}
    recycling = {"records": [
        {"record_id": "RC-5", "source_design_id": "D5", "status": "quarantined"},
        {"record_id": "RC-7", "source_design_id": "D7", "status": "pending_review"},
        {"record_id": "RC-8", "source_design_id": "D8", "status": "pending_analysis"}]}
    store = [
        {"record_id": "RC-5", "source_ref": RUN, "status": "quarantined", "image_uri": "sim://images/D5.png",
         "rejection": {"by": "compliance", "reason": "trademark risk", "stage": "compliance"}, "original": {},
         "analysis": {"recycler_id": "recycler-1", "method": "metadata_cross_reference", "image_inspected": False,
                      "quarantine": True, "suggestions": [{"type": "quarantine", "confidence": 1.0,
                                                           "reasons": ["flagged"], "references": []}]}},
        {"record_id": "RC-7", "source_ref": RUN, "status": "pending_review", "image_uri": "sim://images/D7.png",
         "rejection": {"by": "manager", "reason": "<img src=x onerror=window.pwned=1>", "stage": "approval"},
         "original": {"niche": "cozy autumn", "product_type": "tote"},
         "analysis": {"recycler_id": "compliance-2", "method": "metadata_cross_reference", "image_inspected": False,
                      "suggestions": [{"type": "alternate_product", "target_niche": "cozy autumn",
                                       "target_product": "mug", "confidence": 0.72,
                                       "reasons": ["fit 0.9 on mug"], "references": ["product_fit:cozy autumn:mug"]}]}},
        {"record_id": "RC-8", "source_ref": RUN, "status": "pending_analysis", "image_uri": "sim://images/D8.png",
         "rejection": {"by": "manager", "reason": "low score", "stage": "approval"}, "original": {}, "analysis": None},
        {"record_id": "RC-other", "source_ref": "run_other.json", "status": "pending_review", "analysis": None},
    ]
    designs = design_payload(df, recycling=recycling, team=team, manager=manager)
    html = build_arena_html(designs, team=team, character=character_from_report(manager).to_dict(), run_label=RUN,
                            plans=recycling_plans(recycling, store, RUN))
    return designs, html


def test_full_replay_resolves_with_cooperation_handoffs_transfers_and_plans(browser, tmp_path):
    designs, html = _rich_run()
    page, errors = open_arena(browser, html, tmp_path)
    s = run_until_finished(page)
    assert s["finished"] and s["resolved"] == s["total"] == 8
    expected = {}
    for d in designs:
        expected[d["resolution"]] = expected.get(d["resolution"], 0) + 1
    assert {k: v for k, v in s["res"].items() if v} == expected
    assert expected == {"completed": 4, "quarantined": 1, "held": 1, "pending_reuse": 2}
    for room, info in s["rooms"].items():
        assert info["processed"] == info["expected"] and info["queue"] == 0 and info["jobs"] == 0, room
    agents = {a["id"]: a for a in s["agents"]}
    # Both workers of a department really share the work, as recorded.
    assert agents["prompt-1"]["worked"] == 4 and agents["prompt-2"]["worked"] == 4
    trails = {t["id"]: t["trail"] for t in s["trails"]}
    by_id = {d["id"]: d for d in designs}
    for design_id, trail in trails.items():
        for step in trail:
            room, worker = step.split(":")
            assigned = by_id[design_id]["assigned"].get(room)
            if assigned and room != "compliance":  # compliance-2 is on loan to recycling for part of the run
                assert worker == assigned, (design_id, step)
    assert s["handoffs"] >= 8 * 3
    # Recorded transfers are replayed out and back.
    assert any("compliance-2: compliance → recycling" in t for t in s["transfers"])
    assert any("compliance-2: recycling → compliance" in t for t in s["transfers"])
    assert agents["compliance-2"]["room"] == "compliance" and agents["compliance-2"]["moves"] == 2
    # Recycler reviewed every delivered image and reported the real plan (or its absence).
    plans = {p["design"]: p["text"] for p in s["plans"]}
    assert plans["D7"].startswith("alternate_product → cozy autumn / mug")
    assert plans["D8"] == "not analyzed yet" and plans["D5"].startswith("quarantine")
    # Dr. Cypher made all recorded visits, then returned home.
    cy = s["cypher"]
    assert cy["visited"] == 5 and cy["skipped"] == 0 and cy["room"] == "command" and cy["home"]
    assert any(line.startswith("visit: Recycling Facility") for line in cy["log"])
    # Inspect the facility: real plan details, honest labels, escaped text.
    page.evaluate("() => arenaDebug.select({k: 's', key: 'recycling'})")
    info = page.inner_text("#info")
    assert "alternate_product" in info and "pixels inspected: no" in info and "Not analyzed yet" in info
    assert "simulated asset - no image pixels exist" in info
    assert "other record(s) in the recycling queue" in info and "RC-other" not in info
    assert "<img src=x" in info and page.evaluate("() => window.pwned") is None
    assert page.query_selector("#info img") is None
    page.evaluate("() => arenaDebug.select({k: 'a', id: 'recycler-1'})")
    assert "Recycler" in page.inner_text("#info")
    assert errors == []


def test_reject_all_legacy_run_skips_unreachable_visits_and_returns_home(browser, tmp_path):
    df = pd.DataFrame([{"design_id": f"D{i}", "niche": "n", "compliance_status": "flagged", "approved": False,
                        "profit": 0.0} for i in range(4)])
    manager = {"decisions": [{"stage": "trend", "action": "keep"}, {"stage": "compliance", "action": "reject"},
                             {"stage": "pricing", "action": "reprice"}, {"stage": "approval", "action": "block"}]}
    html = build_arena_html(design_payload(df), character=character_from_report(manager).to_dict(), run_label="old")
    page, errors = open_arena(browser, html, tmp_path)
    s = run_until_finished(page)
    assert s["finished"] and s["res"]["rejected"] == 4
    cy = s["cypher"]
    assert cy["visited"] == 2 and cy["skipped"] == 2 and cy["home"] and cy["room"] == "command"
    assert sum("skipped: pricing visit: no designs reached Pricing Bureau" in x for x in cy["log"]) == 1
    page.evaluate("() => arenaDebug.select({k: 'c'})")
    assert "reconstructed from the manager decision log" in page.inner_text("#info")
    assert errors == []


def test_empty_run_and_missing_workers_never_spin(browser, tmp_path):
    page, errors = open_arena(browser, build_arena_html([]), tmp_path)
    s = run_until_finished(page, limit=30)
    assert s["finished"] and s["total"] == 0 and s["cypher"]["home"]
    df = pd.DataFrame([{"design_id": "D1", "niche": "n", "compliance_status": "pass", "approved": True,
                        "profit": 1.0}])
    team = {"departments": {"prompt": ["p-1"]}}  # custom team without image/compliance/... workers
    page, errors2 = open_arena(browser, build_arena_html(design_payload(df), team=team), tmp_path)
    s = run_until_finished(page)
    assert s["finished"] and s["res"]["completed"] == 1
    assert any(a["id"] == "image-placeholder" and a["synthetic"] for a in s["agents"])
    assert errors == [] and errors2 == []


def test_real_time_loop_moves_agents_and_cypher_and_controls_work(browser, tmp_path):
    _, html = _rich_run()
    page, errors = open_arena(browser, html, tmp_path, width=420)  # narrow screen
    page.click("#play")  # resume the requestAnimationFrame loop
    page.click("#fast")
    start = page.evaluate("() => arenaDebug.summary()")
    page.wait_for_timeout(2500)
    mid = page.evaluate("() => arenaDebug.summary()")
    assert mid["t"] > start["t"] + 2 and mid["spawned"] > start["spawned"]
    assert (mid["cypher"]["x"], mid["cypher"]["y"]) != (start["cypher"]["x"], start["cypher"]["y"])
    assert page.inner_text("#roster").count("·") >= 10  # one chip per worker
    page.click("#play")  # pause
    paused = page.evaluate("() => arenaDebug.summary()")["t"]
    page.wait_for_timeout(500)
    assert page.evaluate("() => arenaDebug.summary()")["t"] == paused
    page.click("#reset")
    assert page.evaluate("() => arenaDebug.summary()")["t"] == 0
    box = page.query_selector("#c").bounding_box()
    assert box["width"] <= 420 and box["height"] > 0
    assert errors == []


def test_image_studio_shows_artist_painting_active_work(browser, tmp_path):
    design = {"id": "D1", "niche": "cats", "flagged": False, "approved": True, "profit": 1.0,
              "path": ["image"], "resolution": "completed"}
    page, errors = open_arena(browser, build_arena_html([design]), tmp_path)
    painting = page.evaluate("""() => {
      const ctx = document.querySelector('#c').getContext('2d');
      const original = ctx.fillText;
      const labels = [];
      ctx.fillText = function(text, ...args) {
        labels.push(String(text));
        return original.call(this, text, ...args);
      };
      arenaDebug.advance(0.2);
      return labels;
    }""")
    assert any(label.startswith("PAINTING · D1") for label in painting)
    assert page.evaluate("() => arenaDebug.summary().rooms.image.jobs") == 1
    assert errors == []
