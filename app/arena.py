"""Fallout Shelter-style simulation arena: layout data + self-contained canvas renderer.

The arena is a *replay* of a recorded run: it animates the run's real
designs, rejections, recycling outcomes, recorded agent transfers and Dr.
Cypher's recorded department visits. It is not a view of live backend work.
"""
import json

from app.sim.team import DEFAULT_WORKERS, agents_for, transfer_events

STATIONS = [
    {"key": "trend", "agent": "TREND", "icon": "🎯", "name": "Trend Lab", "desc": "finds trending niches"},
    {"key": "prompt", "agent": "PROMPT", "icon": "📝", "name": "Prompt Workshop", "desc": "writes product-aware briefs + prompts"},
    {"key": "image", "agent": "IMAGE", "icon": "🎨", "name": "Image Studio", "desc": "generates images"},
    {"key": "compliance", "agent": "COMPLIANCE", "icon": "🛡️", "name": "Compliance Office", "desc": "checks violations"},
    {"key": "mockup", "agent": "MOCKUP", "icon": "📦", "name": "Mockup Assembly", "desc": "selects products"},
    {"key": "pricing", "agent": "PRICING", "icon": "💰", "name": "Pricing Bureau", "desc": "sets prices"},
    {"key": "approval", "agent": "APPROVAL", "icon": "✅", "name": "Approval Gate", "desc": "approves designs"},
    {"key": "simulator", "agent": "SIMULATOR", "icon": "📊", "name": "Market Simulator", "desc": "calculates results"},
]

# Rooms that are not pipeline stages. They are never the "final stage": the
# renderer finds the market simulator by key, not by position.
FACILITIES = [
    {"key": "recycling", "agent": "RECYCLER", "icon": "♻️", "name": "Recycling Facility",
     "desc": "cross-references rejected images for alternate uses"},
]

COLUMNS = 4
ROOM_W, ROOM_H = 210, 150
CORRIDOR_Y = 280
LOWER_CORRIDOR_Y = 530
SHAFT_X = 470  # vertical shaft in the gap between the 2nd and 3rd room columns
TOP_ROW_Y, BOTTOM_ROW_Y = 70, 340
FACILITY_Y, FACILITY_H = 580, 140
CANVAS_W, CANVAS_H = 960, 780
COMMAND = {"key": "command", "name": "Command Center", "x": 20, "y": 6, "w": 920, "h": 52,
           "home": (SHAFT_X, 34), "exit": [(SHAFT_X, 34), (SHAFT_X, 64), (SHAFT_X, CORRIDOR_Y)]}
OPS_BOARD = {"x": 490, "y": FACILITY_Y, "w": 450, "h": FACILITY_H}
HUD = {"x": 20, "y": 732, "w": 920, "h": 40}

# Pipeline rooms that a team department works in (marketing has no room).
ROOM_FOR_DEPARTMENT = {k: k for k in ("trend", "prompt", "image", "compliance", "mockup", "pricing",
                                      "approval", "recycling")}
SYNTHETIC_STAFF = {"trend": "trend-scout", "approval": "approval-desk", "simulator": "market-sim",
                   "recycling": "recycler-1"}


def station_layout():
    """Return room geometry for each station (grid of rooms around a central corridor)."""
    layout = []
    for i, s in enumerate(STATIONS):
        col, row = i % COLUMNS, i // COLUMNS
        x = 20 + col * (ROOM_W + 20)
        y = TOP_ROW_Y if row == 0 else BOTTOM_ROW_Y
        door = (x + ROOM_W // 2, CORRIDOR_Y)
        home = (x + ROOM_W // 2, y + ROOM_H - 40)
        layout.append({**s, "index": i, "x": x, "y": y, "w": ROOM_W, "h": ROOM_H,
                       "door": door, "home": home, "exit": [home, door]})
    return layout


def facility_layout():
    """Extra rooms below the lower corridor, reached through the central shaft."""
    rooms = []
    for i, f in enumerate(FACILITIES):
        x, w = 20 + i * 460, 430
        home = (x + w // 2, FACILITY_Y + FACILITY_H - 50)
        door = (x + w // 2, LOWER_CORRIDOR_Y)
        rooms.append({**f, "index": len(STATIONS) + i, "x": x, "y": FACILITY_Y, "w": w, "h": FACILITY_H,
                      "door": door, "home": home,
                      "exit": [home, door, (SHAFT_X, LOWER_CORRIDOR_Y), (SHAFT_X, CORRIDOR_Y)]})
    return rooms


def room_index():
    rooms = {r["key"]: r for r in station_layout() + facility_layout()}
    rooms["command"] = dict(COMMAND)
    return rooms


def route(src_key, dst_key, rooms=None):
    """Axis-aligned waypoints between any two rooms (stations, facilities or
    the command center) via the corridors. Unknown rooms raise KeyError."""
    rooms = rooms or room_index()
    a, b = rooms[src_key], rooms[dst_key]
    if src_key == dst_key:
        return [tuple(a["home"])]
    points = [tuple(p) for p in a["exit"]] + [tuple(p) for p in reversed(b["exit"])]
    out = []
    for point in points:
        if not out or out[-1] != point:
            out.append(point)
    return out


def find_path(src, dst, layout=None):
    """Waypoints for an agent walking from station src's room to station dst's room via the corridor."""
    layout = layout or station_layout()
    a, b = layout[src], layout[dst]
    if src == dst:
        return [a["home"]]
    return [a["home"], a["door"], b["door"], b["home"]]


RECYCLE_OUTCOME = {
    "pending_analysis": "pending_reuse", "pending_review": "pending_reuse", "reuse_requested": "pending_reuse",
    "reentered_pipeline": "pending_reuse", "quarantined": "quarantined", "archived": "unusable",
    "unusable": "unusable",
}
# Terminal states every design ends in (the HUD/ops board count each one once).
RESOLUTIONS = ("completed", "held", "blocked", "rejected", "pending_reuse", "quarantined", "unusable")
# Pipeline departments whose recorded round-robin assignments can be replayed.
ASSIGNED_STAGES = ("prompt", "image", "compliance", "mockup", "pricing")
_ALL_DESIGN_STAGES = ("compliance", "mockup", "pricing")  # also run on recycled reuse candidates
_TEXT_LIMIT = 240


def _txt(value, limit=_TEXT_LIMIT):
    text = "" if value is None else str(value)
    return text if len(text) <= limit else text[: limit - 1] + "\u2026"


def design_route(flagged, approved, has_record, decision=None, recycle_outcome=None):
    """(rooms visited in order, terminal resolution) for one design.

    Mirrors the recorded outcome: compliance rejects stop at compliance,
    everything else passes mockup/pricing/approval; greenlit designs reach the
    market simulator and rejected art with a recycling record (i.e. an
    existing image) is carried to the Recycling Facility."""
    path = ["trend", "prompt", "image", "compliance"]
    if flagged:
        if has_record:
            return path + ["recycling"], recycle_outcome or "unusable"
        return path, "rejected"
    path += ["mockup", "pricing", "approval"]
    if approved:
        return path + ["simulator"], "completed"
    if has_record:
        return path + ["recycling"], recycle_outcome or "unusable"
    return path, "blocked" if decision == "BLOCK" else "held"


def stage_assignments(design_ids, recycled_ids, team_report):
    """Recorded worker per (design, department) from the team report's
    round-robin ``assignments`` (``AgentTeam.run_stage`` gives design k of a
    stage to worker k % n). Departments whose recorded counts do not match
    are left unassigned rather than guessed."""
    rows_all = [a for a in ((team_report or {}).get("assignments") or []) if isinstance(a, dict)]
    out = {}
    for dept in ASSIGNED_STAGES:
        rows = [a for a in rows_all if a.get("department") == dept]
        if not rows:
            continue
        ids = [i for i in design_ids if dept in _ALL_DESIGN_STAGES or i not in recycled_ids]
        workers = [str(a.get("worker_id")) for a in rows]
        expected = [len(ids[k::len(workers)]) for k in range(len(workers))]
        if [int(a.get("design_count") or 0) for a in rows] != expected:
            continue
        for k, design_id in enumerate(ids):
            out.setdefault(design_id, {})[dept] = workers[k % len(workers)]
    return out


def design_payload(df, limit=40, recycling=None, team=None, manager=None):
    """Reduce a merged designs/results frame to the records the arena animates.

    ``recycling`` is the run payload's ``recycling`` section (absent in older
    runs); rejected designs with a recycling record are carried to the
    Recycling Facility, everything else keeps the old behaviour. ``team`` and
    ``manager`` (run payload sections) add the recorded worker assignments
    and manager decisions when present."""
    by_design = {}
    for record in (recycling or {}).get("records", []) or []:
        if isinstance(record, dict) and record.get("source_design_id"):
            by_design[str(record["source_design_id"])] = record
    scores = (manager or {}).get("design_scores") or {}
    all_ids = [str(i) for i in df["design_id"]] if "design_id" in df else []
    recycled = set()
    if "lineage" in df:
        for design_id, lineage in zip(all_ids, df["lineage"]):
            if isinstance(lineage, dict) and lineage.get("recycled_from"):
                recycled.add(design_id)
    assigned = stage_assignments(all_ids, recycled, team)
    rows = []
    for _, r in df.head(limit).iterrows():
        design_id = str(r["design_id"])
        image_uri = r.get("image_uri") if hasattr(r, "get") else None
        has_image = isinstance(image_uri, str) and bool(image_uri)
        record = by_design.get(design_id)
        status = str(record.get("status")) if record else None
        approved = bool(r["approved"])
        if approved:
            outcome = "completed"
        elif record:
            outcome = RECYCLE_OUTCOME.get(status, "unusable")
        else:
            outcome = "held_or_rejected"
        score = scores.get(design_id) if isinstance(scores.get(design_id), dict) else {}
        decision = str(score["manager_decision"]) if score.get("manager_decision") else None
        flagged = bool(r["compliance_status"] == "flagged")
        path, resolution = design_route(flagged, approved, bool(record), decision,
                                        RECYCLE_OUTCOME.get(status, "unusable") if record else None)
        work = dict(assigned.get(design_id, {}))
        rows.append({
            "id": design_id,
            "niche": str(r["niche"]),
            "flagged": flagged,
            "approved": approved,
            "profit": float(r["profit"]) if r["profit"] == r["profit"] else 0.0,
            "has_image": has_image,
            "recycle_status": status,
            "recycle_record": str(record.get("record_id")) if record else None,
            "outcome": outcome,
            "decision": decision,
            "path": path,
            "resolution": resolution,
            "assigned": work,
        })
    return rows


def _normalise_design(d):
    """Older callers pass rows without ``path``/``resolution``; derive them."""
    d = dict(d)
    if not d.get("path") or d.get("resolution") not in RESOLUTIONS:
        record = d.get("recycle_record")
        path, resolution = design_route(bool(d.get("flagged")), bool(d.get("approved")), bool(record),
                                        d.get("decision"),
                                        RECYCLE_OUTCOME.get(d.get("recycle_status"), "unusable") if record else None)
        d["path"], d["resolution"] = path, resolution
    d.setdefault("assigned", {})
    d["profit"] = float(d.get("profit") or 0.0)
    return d


def recycling_plans(run_recycling=None, store_records=None, run_name=""):
    """The recycler's plans for the selected run's own recycling records.

    Each plan comes from the global recycling queue record with the same
    record ID (created by this run: ``source_ref`` is the run name), falling
    back to the analysis snapshot saved in the run payload. Records from other
    runs or live work are never attributed to this run; they are only
    counted. Returns ``{"plans": {record_id: plan}, "other_queue_records": n}``."""
    run_records = [r for r in ((run_recycling or {}).get("records") or []) if isinstance(r, dict)]
    store = {}
    other = 0
    for rec in store_records or []:
        if not isinstance(rec, dict) or not rec.get("record_id"):
            continue
        if run_name and rec.get("source_ref") != run_name:
            other += 1
            continue
        store[str(rec["record_id"])] = rec
    plans = {}
    for snap in run_records:
        record_id = str(snap.get("record_id") or "")
        if not record_id or record_id in plans:
            continue
        queued = store.get(record_id)
        analysis, source = None, None
        if queued and isinstance(queued.get("analysis"), dict):
            from app.sim.recycling import analysis_summary

            analysis, source = analysis_summary(queued["analysis"]), "recycling queue (current)"
        elif isinstance(snap.get("analysis"), dict):
            analysis, source = snap["analysis"], "run snapshot"
        image_uri = str((queued or {}).get("image_uri") or "")
        rejection = (queued or {}).get("rejection") or {}
        original = (queued or {}).get("original") or {}
        plan = {
            "record_id": _txt(record_id, 40),
            "design_id": _txt(snap.get("source_design_id"), 60),
            "image_uri": _txt(image_uri or "(not in current queue file)", 160),
            "pixels": ("simulated asset - no image pixels exist" if image_uri.startswith("sim://")
                       else "image file - preview on the Recycling page" if image_uri else "unknown"),
            "niche": _txt(original.get("niche"), 80),
            "product": _txt(original.get("product_type"), 40),
            "rejected_by": _txt(rejection.get("by") or snap.get("rejected_by"), 40),
            "stage": _txt(rejection.get("stage"), 40),
            "reason": _txt(rejection.get("reason") or "not recorded"),
            "status_at_run": _txt(snap.get("status"), 40),
            "current_status": _txt(queued.get("status"), 40) if queued else None,
            "analysis_source": source,
            "analysis": None,
        }
        if analysis:
            plan["analysis"] = {
                "recycler_id": _txt(analysis.get("recycler_id"), 40),
                "method": _txt(analysis.get("method"), 60),
                "image_inspected": bool(analysis.get("image_inspected")),
                "quarantine": bool(analysis.get("quarantine")),
                "limitations": _txt(analysis.get("limitations"), 400),
                "suggestions": [{
                    "type": _txt(s.get("type"), 40),
                    "target_niche": _txt(s.get("target_niche"), 80) if s.get("target_niche") else None,
                    "target_product": _txt(s.get("target_product"), 40) if s.get("target_product") else None,
                    "confidence": s.get("confidence") if isinstance(s.get("confidence"), (int, float)) else None,
                    "reasons": [_txt(x) for x in (s.get("reasons") or [])][:3],
                    "references": [_txt(x, 80) for x in (s.get("references") or [])][:4],
                } for s in (analysis.get("suggestions") or [])[:3] if isinstance(s, dict)],
            }
        plans[record_id] = plan
    return {"plans": plans, "other_queue_records": other}


def arena_agents(team_report=None):
    """Agents with stable IDs placed in their department's room at the
    *start* of the run (recorded transfers are then replayed). Rooms with no
    recorded worker get a labelled placeholder so work never waits forever."""
    report = team_report if (team_report or {}).get("departments") else {"departments": DEFAULT_WORKERS}
    agents = agents_for(report)
    events = transfer_events(team_report)
    start = {aid: a.get("current_department") for aid, a in agents.items()}
    for event in reversed(events):
        if event.get("agent_id") in start:
            start[event["agent_id"]] = event.get("from")
    out = []
    for agent_id, agent in sorted(agents.items()):
        dept = start.get(agent_id)
        out.append({"id": str(agent_id), "home_department": str(agent.get("home_department")),
                    "department": str(dept), "room": ROOM_FOR_DEPARTMENT.get(dept), "synthetic": False})
    staffed = {a["room"] for a in out if a["room"]}
    taken = set(agents)
    for room in [s["key"] for s in STATIONS] + [f["key"] for f in FACILITIES]:
        agent_id = SYNTHETIC_STAFF.get(room, f"{room}-placeholder")
        if room not in staffed and agent_id not in taken:
            out.append({"id": agent_id, "home_department": room, "department": room, "room": room,
                        "synthetic": True})
    return out


def arena_transfers(team_report=None):
    out = []
    for event in transfer_events(team_report):
        out.append({"agent_id": str(event.get("agent_id")), "from": ROOM_FOR_DEPARTMENT.get(event.get("from")),
                    "to": ROOM_FOR_DEPARTMENT.get(event.get("to")), "reason": str(event.get("reason", "")),
                    "initiated_by": str(event.get("initiated_by", ""))})
    return out


def _json_for_script(value):
    """JSON safe to embed inside a <script> element."""
    return (json.dumps(value).replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")
            .replace("\u2028", "\\u2028").replace("\u2029", "\\u2029"))


def _cypher_config(character):
    visits = []
    for v in character.get("visits", []) or []:
        if not isinstance(v, dict):
            continue
        visits.append({"room": ROOM_FOR_DEPARTMENT.get(v.get("department")),
                       "department": _txt(v.get("department"), 40),
                       "purpose": _txt(v.get("purpose", "")), "line": _txt(v.get("line", "")),
                       "source": "reconstructed" if v.get("source") == "reconstructed" else "recorded",
                       "design_ids": [_txt(i, 40) for i in (v.get("design_ids") or [])[:8]]})
    if not visits:
        basis = "none"
    elif any(v["source"] == "reconstructed" for v in visits):
        basis = "reconstructed"
    else:
        basis = "recorded"
    return {
        "name": str(character.get("display_name") or "Dr. Cypher"),
        "mood": str(character.get("mood") or "focused"),
        "line": str(character.get("line") or ""),
        "basis": basis,
        "visits": visits,
    }


def build_arena_html(designs, team=None, character=None, run_label="", plans=None):
    """``team`` is the run's team report, ``character`` Dr. Cypher's
    ``to_dict()`` and ``plans`` the output of ``recycling_plans``; all are
    optional so older runs still render."""
    rooms = room_index()
    character = character or {}
    designs = [_normalise_design(d) for d in designs]
    expected = {}
    for d in designs:
        for room in d["path"]:
            expected[room] = expected.get(room, 0) + 1
    plans = plans or {}
    config = {
        "stations": station_layout(),
        "facilities": facility_layout(),
        "rooms": {k: {"key": k, "home": v["home"], "exit": v["exit"]} for k, v in rooms.items()},
        "command": COMMAND,
        "ops": OPS_BOARD,
        "hud": HUD,
        "designs": designs,
        "expected": expected,
        "plans": plans.get("plans") or {},
        "otherQueue": int(plans.get("other_queue_records") or 0),
        "agents": arena_agents(team),
        "transfers": arena_transfers(team),
        "offsite": sorted({a for a, info in agents_for(team).items()
                           if ROOM_FOR_DEPARTMENT.get(info.get("current_department")) is None}),
        "cypher": _cypher_config(character),
        "label": str(run_label or "recorded run"),
        "w": CANVAS_W, "h": CANVAS_H, "corridorY": CORRIDOR_Y, "lowerY": LOWER_CORRIDOR_Y, "shaftX": SHAFT_X,
    }
    return ARENA_TEMPLATE.replace("__CONFIG__", _json_for_script(config))


ARENA_TEMPLATE = r"""
<div id="arena" style="background:#0a0e27;color:#00ff41;font-family:'Courier New',monospace;max-width:960px;margin:0 auto;">
<div id="bar" style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;padding:6px 0;">
  <button id="play">⏸ PAUSE</button><button id="slow">⏪ SLOWER</button><button id="fast">⏩ FASTER</button>
  <button id="reset">🔄 RESTART</button><span id="speed" style="color:#00ccff">SPEED x2</span>
  <span id="replay" style="color:#ff6b9d"></span>
  <span id="metrics" style="margin-left:auto;color:#ffaa00"></span>
</div>
<canvas id="c" style="width:100%;display:block;border:2px solid #00ff41;border-radius:8px;box-shadow:0 0 20px rgba(0,255,65,.4);cursor:pointer"></canvas>
<div id="roster" style="display:flex;flex-wrap:wrap;gap:4px;margin-top:6px;font-size:11px"></div>
<div id="info" style="margin-top:6px;border:2px solid #00ccff;border-radius:8px;padding:8px;color:#00ccff;min-height:44px;max-height:190px;overflow:auto;font-size:12px">
Click an agent, Dr. Cypher or a room (try the ♻️ Recycling Facility) to inspect it.</div>
</div>
<style>#bar button{background:linear-gradient(135deg,#00ff41,#00cc33);color:#0a0e27;border:0;border-radius:6px;padding:6px 12px;font-weight:bold;font-family:inherit;cursor:pointer}
#roster span{border:1px solid #2a3a6a;border-radius:4px;padding:1px 5px;color:#cfe3ff;cursor:pointer}#info ul{margin:2px 0;padding-left:18px}</style>
<script>
const CFG = __CONFIG__;
const S = CFG.stations, F = CFG.facilities, D = CFG.designs, R = CFG.rooms, P = CFG.plans || {};
const ROOMS = S.concat(F), BY = {};
ROOMS.forEach(r => BY[r.key] = r);
const FINAL = 'simulator', RECYCLE = 'recycling';
const cv = document.getElementById('c'), ctx = cv.getContext('2d');
cv.width = CFG.w; cv.height = CFG.h;
const WALK = 220, DUR = 1.0, SPAWN = 1.0, TALK = 2.6, PATROL_TALK = 1.8;
const RES = {completed: ['✔ completed', '#00ff41'], held: ['⏸ held for human review', '#ffaa00'],
  blocked: ['⛔ blocked (no image record)', '#ff8888'], rejected: ['✖ compliance reject (no record)', '#ff8888'],
  pending_reuse: ['♻ pending reuse review', '#7dff9b'], quarantined: ['☣ quarantined', '#ff4444'], unusable: ['🗄 unusable / archived', '#8a8a8a']};
const BASIS = {recorded: 'visits recorded by this run\'s manager', reconstructed: 'visits reconstructed from the manager decision log (older run)',
  none: 'no recorded manager visits for this run: patrols only, not recorded decisions'};
let speed = 2, playing = true, sel = null, st, last = performance.now(), infoT = 0;
document.getElementById('replay').textContent = 'REPLAY of ' + CFG.label + ' (recorded outcomes, timed animation, not live work)';

function esc(v) { return String(v === null || v === undefined ? '' : v).replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c])); }
function route(a, b) {
  if (a === b) return [R[a].home.slice()];
  const pts = R[a].exit.concat(R[b].exit.slice().reverse()), out = [];
  pts.forEach(p => { const l = out[out.length - 1]; if (!l || l[0] !== p[0] || l[1] !== p[1]) out.push(p.slice()); });
  return out;
}
function name(key) { return BY[key] ? BY[key].name : key === 'command' ? 'Command Center' : String(key); }
function nextStop(d, key) { const i = d.path.indexOf(key); return i >= 0 && i < d.path.length - 1 ? d.path[i + 1] : null; }
function staff(key) { return st.agents.filter(a => a.room === key); }
function present(key) { return st.agents.filter(a => a.room === key && a.state === 'idle'); }
function slot(ag) {
  const mates = staff(ag.room), k = mates.indexOf(ag), h = R[ag.room].home;
  return [h[0] + (k - (mates.length - 1) / 2) * 46, h[1]];
}
function log(msg) { st.log.unshift('[' + st.t.toFixed(1) + 's] ' + msg); if (st.log.length > 60) st.log.pop(); }
function planText(rec) {
  const p = P[rec];
  if (!p) return 'no record details';
  const a = p.analysis;
  if (!a) return 'not analyzed yet';
  const s = (a.suggestions || [])[0];
  if (!s) return 'analyzed: no suggestions';
  return s.type + (s.target_product || s.target_niche ? ' → ' + (s.target_niche || '-') + ' / ' + (s.target_product || '-') : '') + (s.confidence !== null ? ' (' + s.confidence + ')' : '');
}
function newAgent(a) {
  return {id: a.id, home: a.home_department, room: a.room, synthetic: a.synthetic, x: 0, y: 0, state: 'idle', job: null, pkg: null, wp: [], dest: null,
    delivered: 0, worked: 0, dist: 0, moves: 0, task: '', lastTask: ''};
}
function reset() {
  st = {t: 0, spawnT: SPAWN, next: 0, spawned: 0, resolved: 0, res: {}, profit: 0, fx: [], rooms: {}, log: [], handoffs: 0, plansDone: [], notes: [],
    D: D.map(d => Object.assign({}, d, {trail: [], done: false})),
    xfer: CFG.transfers.map(e => Object.assign({fired: false}, e)), xferLog: []};
  Object.keys(RES).forEach(k => st.res[k] = 0);
  ROOMS.forEach(r => st.rooms[r.key] = {queue: [], jobs: [], processed: 0, arrived: 0, expected: (CFG.expected || {})[r.key] || 0});
  st.agents = CFG.agents.filter(a => a.room && R[a.room]).map(newAgent);
  st.agents.forEach(a => { const p = slot(a); a.x = p[0]; a.y = p[1]; });
  const ch = R.command.home;
  st.cy = {x: ch[0], y: ch[1], room: 'command', vi: 0, state: 'idle', wp: [], talk: 0, wait: 0, kind: '', target: null, line: CFG.cypher.line,
    feedback: '', purpose: 'At the command center', log: [], visited: 0, skipped: 0, patrols: 0, lastPatrol: null, home: true, homeLogged: false};
  if (CFG.cypher.basis === 'none') st.cy.purpose = 'No recorded manager visits: patrolling active departments';
}
function allResolved() { return st.resolved >= st.D.length; }
function finishAll() { return allResolved() && st.agents.every(a => a.state === 'idle'); }
function fx(x, y, txt, c) { st.fx.push({x, y, t: 0, txt, c}); }
function walk(ag, pts) { ag.wp = pts; }
function arrive(d, key) { const sn = st.rooms[key]; sn.queue.push(d); sn.arrived++; d.at = key; }
function placeholder(key) {
  const id = key + '-placeholder';
  if (st.agents.some(a => a.id === id)) { st.agents.find(a => a.id === id).room = key; return; }
  const ag = newAgent({id, home_department: key, room: key, synthetic: true});
  st.agents.push(ag); const p = slot(ag); ag.x = p[0]; ag.y = p[1];
  st.notes.push(name(key) + ' had queued work but no worker: placeholder ' + id);
  log('No worker in ' + name(key) + ' → arena placeholder ' + id + ' staffed it');
}
function resolve(d, key) {
  const r = BY[key], hx = r.home[0], hy = r.home[1] - 46;
  d.done = true; st.resolved++; st.res[d.resolution] = (st.res[d.resolution] || 0) + 1;
  if (d.resolution === 'completed') { st.profit += d.profit; fx(hx, hy, '+$' + d.profit.toFixed(0), '#00ff41'); }
  else if (d.resolution === 'held') fx(hx, hy, 'HOLD', '#ffaa00');
  else if (d.resolution === 'quarantined') fx(hx, hy, '☣ QUARANTINE', '#ff4444');
  else if (d.resolution === 'pending_reuse') fx(hx, hy, '♻ PENDING REUSE', '#00ff41');
  else if (d.resolution === 'unusable') fx(hx, hy, '🗄 UNUSABLE', '#8a8a8a');
  else fx(hx, hy, '✖', '#ff4444');
  log(d.id + ' resolved at ' + name(key) + ': ' + RES[d.resolution][0]);
}
function complete(key, ag, d) {
  const r = BY[key];
  d.trail.push(key + ':' + ag.id);
  if (key === RECYCLE) {
    const text = planText(d.recycle_record);
    st.plansDone.push({design: d.id, record: d.recycle_record, by: ag.id, text});
    ag.lastTask = 'reviewed ' + d.id + ' (' + d.recycle_record + '): ' + text;
    fx(r.home[0] - 60, r.home[1] - 66, '📋 ' + text.slice(0, 34), '#7dff9b');
  } else ag.lastTask = 'finished ' + d.id + ' in ' + name(key);
  const nxt = nextStop(d, key);
  if (!nxt) { resolve(d, key); return; }
  if (nxt === RECYCLE) fx(r.home[0], r.home[1] - 46, '♻ to recycling', '#ffaa00');
  ag.pkg = d; ag.state = 'deliver'; ag.dest = nxt; ag.task = 'carrying ' + d.id + ' → ' + name(nxt);
  walk(ag, route(key, nxt).slice(1));
}
function tickRoom(key, dt) {
  const sn = st.rooms[key];
  if (sn.queue.length && !staff(key).length) placeholder(key);
  present(key).sort((a, b) => a.worked - b.worked).forEach(ag => {
    if (!sn.queue.length) return;
    const ids = staff(key).map(a => a.id);
    let i = sn.queue.findIndex(d => d.assigned[key] === ag.id);
    if (i < 0) i = sn.queue.findIndex(d => !d.assigned[key] || ids.indexOf(d.assigned[key]) < 0);
    if (i < 0) return;  // the rest is reserved for its recorded worker, who is still in this room
    const d = sn.queue.splice(i, 1)[0], w = d.assigned[key], covering = w && w !== ag.id ? w : null;
    const job = {d, ag, prog: 0, covering};
    sn.jobs.push(job); ag.state = 'work'; ag.job = job;
    ag.task = (key === RECYCLE ? 'reviewing ' : 'working on ') + d.id + (covering ? ' (covering for ' + covering + ')' : '');
  });
  sn.jobs.slice().forEach(job => {
    job.prog += dt / DUR;
    if (job.prog < 1) return;
    sn.jobs.splice(sn.jobs.indexOf(job), 1); sn.processed++;
    const ag = job.ag; ag.state = 'idle'; ag.job = null; ag.worked++; ag.task = '';
    complete(key, ag, job.d);
  });
}
function fireTransfers() {
  const waiting = new Set();  // each agent's transfers replay strictly in recorded order
  st.xfer.forEach(e => {
    if (e.fired) return;
    if (waiting.has(e.agent_id)) return;
    waiting.add(e.agent_id);
    const ag = st.agents.find(a => a.id === e.agent_id);
    if (!ag || !e.to || !R[e.to] || ag.room === e.to) {
      e.fired = true; e.skipped = true;
      st.xferLog.push(e.agent_id + ' → ' + (e.to || 'no arena room') + ' (' + e.initiated_by + ', not animated)');
      return;
    }
    const due = e.initiated_by === 'auto:demand' ? st.rooms[e.to].arrived > 0 : e.initiated_by === 'auto:end_of_shift' ? allResolved() : st.t > 1;
    if (!due || ag.state !== 'idle') return;
    e.fired = true;
    const from = ag.room; ag.room = e.to; ag.moves++; ag.state = 'transfer'; ag.task = 'transferring to ' + name(e.to);
    walk(ag, route(from, e.to).slice(1).concat([slot(ag)]));
    st.xferLog.push(ag.id + ': ' + from + ' → ' + e.to + ' (' + e.initiated_by + ')');
    log('Transfer ' + ag.id + ': ' + name(from) + ' → ' + name(e.to) + ' (' + e.initiated_by + (e.reason ? ', ' + e.reason : '') + ')');
    fx(ag.x, ag.y - 30, '🚶 transfer', '#ff6b9d');
  });
}
function move(o, dt) {
  let step = WALK * dt;
  while (step > 0 && o.wp.length) {
    const [tx, ty] = o.wp[0], dx = tx - o.x, dy = ty - o.y, d = Math.hypot(dx, dy);
    if (d <= step) { o.x = tx; o.y = ty; o.wp.shift(); o.dist = (o.dist || 0) + d; step -= d; }
    else { o.x += dx / d * step; o.y += dy / d * step; o.dist = (o.dist || 0) + step; step = 0; }
  }
  return !o.wp.length;
}
function moveAgents(dt) {
  st.agents.forEach(ag => {
    if (ag.state === 'idle' || ag.state === 'work') return;
    if (!move(ag, dt)) return;
    if (ag.state === 'deliver') {
      const d = ag.pkg; arrive(d, ag.dest); st.handoffs++;
      log(ag.id + ' handed ' + d.id + ' to ' + name(ag.dest));
      ag.pkg = null; ag.delivered++; ag.lastTask = 'delivered ' + d.id + ' to ' + name(ag.dest); fx(ag.x, ag.y - 30, '📨 ' + d.id, '#00ccff');
      ag.state = 'return'; ag.task = 'returning to ' + name(ag.room); walk(ag, route(ag.dest, ag.room).slice(1).concat([slot(ag)]));
    } else { ag.state = 'idle'; ag.task = ''; const p = slot(ag); ag.x = p[0]; ag.y = p[1]; }
  });
  st.agents.forEach(ag => { if (ag.state === 'idle' || ag.state === 'work') { const p = slot(ag); ag.x = p[0]; ag.y = p[1]; } });
}
// --- Dr. Cypher -----------------------------------------------------------
function observe(room) {
  const sn = st.rooms[room];
  if (!sn) return 'Command center';
  let t = name(room) + ': ' + sn.processed + '/' + sn.expected + ' done, ' + sn.queue.length + ' queued';
  const busy = sn.jobs.map(j => j.ag.id + ' on ' + j.d.id + ' ' + Math.round(j.prog * 100) + '%');
  if (busy.length) t += '; ' + busy.join(', ');
  else if (sn.queue.length) t += '; waiting for a free worker';
  else if (sn.expected && sn.processed >= sn.expected) t += '; all assigned work complete ✔';
  if (room === RECYCLE && st.plansDone.length) { const p = st.plansDone[st.plansDone.length - 1]; t += '; last plan ' + p.design + ': ' + p.text; }
  return t;
}
function cyLog(kind, text) { st.cy.log.push({kind, text, t: st.t}); log('Dr. Cypher ' + kind + ': ' + text); }
function cyGo(room, kind, v) {
  const cy = st.cy;
  let wp = route(cy.room, room).slice(1);
  if (!wp.length) wp = [R[room].home.slice()];
  if (room !== 'command') wp[wp.length - 1][1] -= 44;
  cy.wp = wp; cy.kind = kind; cy.target = v; cy.state = 'walk'; cy.room = room; cy.home = false;
  cy.purpose = (kind === 'visit' ? 'Heading to ' + name(room) + ': ' + v.purpose : kind === 'patrol' ? 'Patrolling ' + name(room) + ' (replay check, not a recorded decision)' : 'Walking back to the command center');
}
function skipVisit(v, why) {
  st.cy.vi++; st.cy.skipped++;
  cyLog('skipped', (v.department || v.room || '?') + ' visit: ' + why + ' (recorded line kept in the report only)');
}
function patrol() {
  const cy = st.cy, busy = ROOMS.filter(r => { const sn = st.rooms[r.key]; return (sn.jobs.length || sn.queue.length) && r.key !== cy.room && r.key !== cy.lastPatrol; });
  if (!busy.length) return false;
  busy.sort((a, b) => (st.rooms[b.key].queue.length + st.rooms[b.key].jobs.length) - (st.rooms[a.key].queue.length + st.rooms[a.key].jobs.length));
  cy.lastPatrol = busy[0].key; cyGo(busy[0].key, 'patrol', null);
  return true;
}
function cypherTick(dt) {
  const cy = st.cy, V = CFG.cypher.visits, done = allResolved();
  if (cy.state !== 'idle') return;
  if (cy.wait > 0) { cy.wait -= dt; return; }
  let waitingFor = null;
  while (cy.vi < V.length) {
    const v = V[cy.vi];
    if (!v.room || !R[v.room]) { skipVisit(v, 'that department has no arena room'); continue; }
    const sn = st.rooms[v.room];
    if (!sn.expected) { skipVisit(v, 'no designs reached ' + name(v.room) + ' in this replay'); continue; }
    if (sn.arrived > 0) { cyGo(v.room, 'visit', v); return; }
    if (done) { skipVisit(v, name(v.room) + ' never received work'); continue; }
    waitingFor = v; break;
  }
  if (!done) {
    if (!patrol()) { cy.wait = 0.4; cy.purpose = waitingFor ? 'Waiting for work to reach ' + name(waitingFor.room) : 'Watching the floor'; }
    return;
  }
  if (cy.room !== 'command') { cyGo('command', 'home', null); return; }
  if (!cy.homeLogged && finishAll()) {
    cy.homeLogged = true; cy.home = true; cy.line = CFG.cypher.line || cy.line;
    cy.purpose = 'Back at the command center: all ' + st.D.length + ' design(s) resolved';
    cyLog('home', 'returned to the command center; ' + cy.visited + ' recorded visit(s), ' + cy.skipped + ' skipped, ' + cy.patrols + ' patrol(s)');
  }
}
function updateCypher(dt) {
  const cy = st.cy;
  if (cy.state === 'walk' && move(cy, dt)) {
    if (cy.kind === 'visit') {
      cy.state = 'talk'; cy.talk = TALK; cy.line = cy.target.line || cy.target.purpose; cy.feedback = observe(cy.room);
      cy.purpose = cy.target.purpose + ' (' + cy.target.source + ')';
      cyLog('visit', name(cy.room) + ' — "' + cy.line + '" | observed: ' + cy.feedback);
    } else if (cy.kind === 'patrol') {
      cy.state = 'talk'; cy.talk = PATROL_TALK; cy.feedback = observe(cy.room); cy.line = '👀 ' + cy.feedback; cy.patrols++;
      cyLog('patrol', cy.feedback);
    } else { cy.state = 'idle'; }
  } else if (cy.state === 'talk') {
    cy.talk -= dt;
    if (cy.talk <= 0) { cy.state = 'idle'; if (cy.kind === 'visit') { cy.vi++; cy.visited++; } else cy.wait = 0.6; }
  }
  cypherTick(dt);
}
function update(dt) {
  st.t += dt; st.spawnT += dt;
  if (st.next < st.D.length && st.spawnT >= SPAWN) { st.spawnT = 0; const d = st.D[st.next++]; arrive(d, d.path[0]); st.spawned++; }
  fireTransfers();
  ROOMS.forEach(r => tickRoom(r.key, dt));
  moveAgents(dt);
  updateCypher(dt);
  st.fx.forEach(f => f.t += dt); st.fx = st.fx.filter(f => f.t < 1.4);
}
// --- drawing ----------------------------------------------------------------
function status(key) {
  const sn = st.rooms[key];
  if (sn.jobs.length) return 'BUSY';
  if (sn.queue.length) return 'WAITING FOR WORKER';
  if (!sn.expected) return 'NO WORK THIS RUN';
  return sn.processed >= sn.expected ? 'COMPLETE' : 'IDLE';
}
const COL = {BUSY: '#ffaa00', IDLE: '#4a5a7a', COMPLETE: '#00ff41', 'WAITING FOR WORKER': '#00ccff', 'NO WORK THIS RUN': '#3a4460'};
function glowRect(x, y, w, h, c) { ctx.shadowColor = c; ctx.shadowBlur = 12; ctx.strokeStyle = c; ctx.lineWidth = 2; ctx.strokeRect(x, y, w, h); ctx.shadowBlur = 0; }
function clip(t, n) { t = String(t); return t.length > n ? t.slice(0, n - 1) + '…' : t; }
function roundedPath(x, y, w, h, r) {
  ctx.beginPath(); ctx.moveTo(x + r, y); ctx.arcTo(x + w, y, x + w, y + h, r);
  ctx.arcTo(x + w, y + h, x, y + h, r); ctx.arcTo(x, y + h, x, y, r);
  ctx.arcTo(x, y, x + w, y, r); ctx.closePath();
}
function panel(x, y, w, h, top, bottom, stroke, r) {
  const g = ctx.createLinearGradient(x, y, x, y + h); g.addColorStop(0, top); g.addColorStop(1, bottom);
  roundedPath(x, y, w, h, r || 8); ctx.fillStyle = g; ctx.fill();
  if (stroke) { ctx.strokeStyle = stroke; ctx.lineWidth = 1.5; ctx.stroke(); }
}
function drawBackdrop() {
  const g = ctx.createLinearGradient(0, 0, CFG.w, CFG.h);
  g.addColorStop(0, '#10172d'); g.addColorStop(.52, '#18233d'); g.addColorStop(1, '#10182b');
  ctx.fillStyle = g; ctx.fillRect(0, 0, CFG.w, CFG.h);
  const glow = ctx.createRadialGradient(CFG.shaftX, CFG.corridorY, 10, CFG.shaftX, CFG.corridorY, 560);
  glow.addColorStop(0, 'rgba(72,129,166,.12)'); glow.addColorStop(1, 'rgba(10,14,39,0)');
  ctx.fillStyle = glow; ctx.fillRect(0, 58, CFG.w, CFG.h - 58);
}
function drawCommand() {
  const c = CFG.command;
  panel(c.x, c.y, c.w, c.h, '#26364f', '#131b31', '#e28aac', 10);
  ctx.fillStyle = 'rgba(255,255,255,.05)'; ctx.fillRect(c.x + 12, c.y + 7, c.w - 24, 1);
  ctx.fillStyle = '#ff6b9d'; ctx.font = 'bold 13px Courier New'; ctx.fillText('🧪 COMMAND CENTER', 36, 26);
  ctx.fillStyle = '#00ccff'; ctx.font = '11px Courier New'; ctx.fillText(clip(CFG.cypher.name + ' · mood: ' + CFG.cypher.mood + ' · ' + CFG.cypher.basis, 52), 36, 44);
  ctx.fillStyle = '#00ff41'; ctx.font = '12px Courier New'; ctx.fillText(clip('"' + st.cy.line + '"', 52), 504, 30);
  ctx.fillStyle = '#8fa3c7'; ctx.font = '10px Courier New'; ctx.fillText(clip(st.cy.purpose, 70), 504, 47);
}
function drawCypher() {
  const cy = st.cy, x = cy.x, y = cy.y + (cy.state === 'walk' ? Math.sin(st.t * 12) * 2 : 0);
  ctx.fillStyle = 'rgba(0,0,0,.3)'; ctx.beginPath(); ctx.ellipse(x, y + 17, 13, 4, 0, 0, 7); ctx.fill();
  panel(x - 10, y + 1, 20, 17, '#f1f4ec', '#9cb4be', null, 7);
  ctx.fillStyle = '#ffd9b3'; ctx.beginPath(); ctx.arc(x, y - 7, 9, 0, 7); ctx.fill();
  ctx.fillStyle = '#4da6ff'; ctx.beginPath(); ctx.arc(x, y - 10, 9, Math.PI, Math.PI * 2); ctx.fill();
  ctx.fillStyle = '#172540'; ctx.fillRect(x - 6, y - 7, 5, 3); ctx.fillRect(x + 1, y - 7, 5, 3);
  ctx.strokeStyle = '#172540'; ctx.lineWidth = 1; ctx.beginPath(); ctx.moveTo(x - 1, y - 6); ctx.lineTo(x + 1, y - 6); ctx.stroke();
  ctx.strokeStyle = sel && sel.k === 'c' ? '#fff' : '#ff6b9d'; ctx.lineWidth = 2; ctx.beginPath(); ctx.arc(x, y, 22, 0, 7); ctx.stroke();
  ctx.font = 'bold 9px Courier New'; ctx.textAlign = 'center'; ctx.fillStyle = '#ff6b9d'; ctx.fillText('DR. CYPHER', x, y + 32); ctx.textAlign = 'left';
  if (cy.state === 'talk') {
    ctx.font = '11px Courier New';
    const t = clip(cy.line, 58), w = ctx.measureText(t).width + 16, bx = Math.min(Math.max(20, x - w / 2), CFG.w - 20 - w);
    ctx.fillStyle = 'rgba(18,24,58,.95)'; ctx.fillRect(bx, y - 52, w, 20); glowRect(bx, y - 52, w, 20, cy.kind === 'patrol' ? '#00ccff' : '#ff6b9d');
    ctx.fillStyle = '#ffffff'; ctx.fillText(t, bx + 8, y - 38);
  }
}
function drawRoom(r) {
  const sn = st.rooms[r.key], stt = status(r.key), c = COL[stt], fac = r.key === RECYCLE;
  panel(r.x, r.y, r.w, r.h, fac ? '#254538' : '#26344b', fac ? '#14261f' : '#151e32',
    sel && sel.k === 's' && sel.key === r.key ? '#ffffff' : c, 9);
  ctx.fillStyle = 'rgba(255,255,255,.08)'; ctx.fillRect(r.x + 8, r.y + 43, r.w - 16, 1);
  ctx.fillStyle = 'rgba(3,8,20,.2)'; ctx.fillRect(r.x + 8, r.y + r.h - 13, r.w - 16, 5);
  ctx.fillStyle = fac ? 'rgba(125,255,155,.28)' : 'rgba(116,193,226,.22)';
  ctx.fillRect(r.x + 12, r.y + r.h - 12, Math.max(8, (r.w - 24) * (sn.expected ? sn.processed / sn.expected : 0)), 3);
  ctx.fillStyle = fac ? '#7dff9b' : '#00ccff'; ctx.font = 'bold 13px Courier New'; ctx.fillText(r.icon + ' ' + r.name, r.x + 8, r.y + 20);
  ctx.fillStyle = c; ctx.font = '11px Courier New'; ctx.fillText('● ' + stt, r.x + 8, r.y + 36);
  ctx.fillStyle = '#ffaa00'; ctx.fillText('queue ' + sn.queue.length + ' · done ' + sn.processed + '/' + sn.expected + ' · staff ' + staff(r.key).length, r.x + 8, r.y + 52);
  sn.jobs.slice(0, 3).forEach((j, i) => {
    const y = r.y + 58 + i * 13, w = fac ? 150 : r.w - 16;
    ctx.fillStyle = '#0a0e27'; ctx.fillRect(r.x + 8, y, w, 10);
    ctx.fillStyle = '#00ff41'; ctx.fillRect(r.x + 8, y, w * Math.min(j.prog, 1), 10);
    ctx.fillStyle = '#ffffff'; ctx.font = '9px Courier New'; ctx.fillText(clip(j.d.id + ' · ' + j.ag.id, 30), r.x + 11, y + 8);
  });
  if (fac) {
    ctx.fillStyle = '#7dff9b'; ctx.font = '10px Courier New';
    ctx.fillText('plans reviewed: ' + st.plansDone.length + '/' + sn.expected + ' (click for details)', r.x + 170, r.y + 66);
    const lp = st.plansDone[st.plansDone.length - 1];
    if (lp) ctx.fillText(clip('last: ' + lp.design + ' → ' + lp.text, 40), r.x + 170, r.y + 80);
  }
}
function drawOps() {
  const o = CFG.ops;
  panel(o.x, o.y, o.w, o.h, '#23354a', '#121d30', '#53b7cb', 9);
  ctx.fillStyle = '#00ccff'; ctx.font = 'bold 12px Courier New'; ctx.fillText('📋 OPS BOARD (this run) · handoffs: ' + st.handoffs, o.x + 10, o.y + 18);
  ctx.font = '11px Courier New';
  Object.keys(RES).forEach((k, i) => { ctx.fillStyle = RES[k][1]; ctx.fillText(clip(RES[k][0] + ': ' + st.res[k], 30), o.x + 10 + (i % 2) * 215, o.y + 36 + Math.floor(i / 2) * 15); });
  ctx.fillStyle = '#ff6b9d'; ctx.fillText(clip('Transfers: ' + (st.xferLog.length ? st.xferLog.join(' | ') : (CFG.transfers.length ? 'pending' : 'none recorded')), 62), o.x + 10, o.y + 104);
  const extra = st.notes.length ? st.notes[st.notes.length - 1] : CFG.offsite.length ? 'No arena room: ' + CFG.offsite.join(', ') : (st.log[0] || '');
  ctx.fillStyle = '#8fa3c7'; ctx.fillText(clip(extra, 62), o.x + 10, o.y + 122);
}
function pkg(x, y) { ctx.shadowColor = '#00ccff'; ctx.shadowBlur = 10; ctx.fillStyle = '#00ccff'; ctx.fillRect(x - 5, y - 5, 10, 10); ctx.shadowBlur = 0; }
function draw() {
  drawBackdrop();
  panel(20, CFG.corridorY - 30, 920, 60, '#29364a', '#1b293b', '#354962', 8);
  panel(20, CFG.lowerY - 25, 920, 50, '#29364a', '#1b293b', '#354962', 8);
  panel(CFG.shaftX - 10, 58, 20, CFG.lowerY - 58, '#29364a', '#1b293b', '#354962', 6);
  ctx.strokeStyle = 'rgba(139,190,200,.28)'; ctx.setLineDash([8, 8]); ctx.beginPath();
  ctx.moveTo(20, CFG.corridorY); ctx.lineTo(940, CFG.corridorY); ctx.moveTo(20, CFG.lowerY); ctx.lineTo(940, CFG.lowerY); ctx.moveTo(CFG.shaftX, 58); ctx.lineTo(CFG.shaftX, CFG.lowerY); ctx.stroke(); ctx.setLineDash([]);
  drawCommand(); ROOMS.forEach(drawRoom); drawOps();
  st.agents.forEach(a => {
    const room = BY[a.room] || BY[S[0].key], bob = a.state === 'idle' || a.state === 'work' ? 0 : Math.sin(st.t * 14) * 3, away = a.room !== a.home;
    const ring = a.synthetic ? '#8fa3c7' : away ? '#ff6b9d' : '#00ff41';
    ctx.fillStyle = 'rgba(0,0,0,.32)'; ctx.beginPath(); ctx.ellipse(a.x, a.y + bob + 16, 12, 4, 0, 0, 7); ctx.fill();
    const avatar = ctx.createRadialGradient(a.x - 5, a.y + bob - 7, 1, a.x, a.y + bob, 16);
    avatar.addColorStop(0, '#52718a'); avatar.addColorStop(1, '#17253b');
    ctx.shadowColor = ring; ctx.shadowBlur = 10; ctx.fillStyle = avatar;
    ctx.strokeStyle = sel && sel.k === 'a' && sel.id === a.id ? '#fff' : ring; ctx.lineWidth = 2;
    ctx.beginPath(); ctx.arc(a.x, a.y + bob, 15, 0, 7); ctx.fill(); ctx.stroke(); ctx.shadowBlur = 0;
    if (a.job) { ctx.strokeStyle = '#ffaa00'; ctx.lineWidth = 3; ctx.beginPath(); ctx.arc(a.x, a.y, 19, -Math.PI / 2, -Math.PI / 2 + Math.PI * 2 * Math.min(a.job.prog, 1)); ctx.stroke(); }
    ctx.font = '15px serif'; ctx.textAlign = 'center'; ctx.fillStyle = '#fff'; ctx.fillText((BY[a.home] || room).icon, a.x, a.y + bob + 5);
    ctx.font = '9px Courier New'; ctx.fillStyle = ring; ctx.fillText(clip(a.id, 14), a.x, a.y + bob + 27);
    const tag = a.job ? a.job.d.id : a.pkg ? a.pkg.id : '';
    if (tag) { ctx.fillStyle = '#ffaa00'; ctx.fillText(clip(tag, 12), a.x, a.y + bob - 22); }
    if (a.pkg) pkg(a.x + 14, a.y + bob - 14);
    ctx.textAlign = 'left';
  });
  drawCypher();
  st.fx.forEach(f => { ctx.globalAlpha = Math.max(0, 1 - f.t / 1.4); ctx.fillStyle = f.c; ctx.font = 'bold 13px Courier New'; ctx.fillText(f.txt, f.x - 20, f.y - f.t * 30); ctx.globalAlpha = 1; });
  const h = CFG.hud;
  panel(h.x, h.y, h.w, h.h, '#23354a', '#121d30', '#53b7cb', 9);
  ctx.fillStyle = '#00ccff'; ctx.font = '12px Courier New';
  ctx.fillText(clip('FLOW: ' + st.spawned + '/' + st.D.length + ' entered → ' + st.resolved + ' resolved (' + st.res.completed + ' completed, ' + st.res.held + ' held, ' +
    (st.res.pending_reuse + st.res.quarantined + st.res.unusable) + ' recycled, ' + (st.res.blocked + st.res.rejected) + ' rejected) | ' + (finishAll() ? 'ALL DESIGNS RESOLVED' : 'IN PROGRESS'), 124), h.x + 12, h.y + 25);
  document.getElementById('metrics').textContent = 'Profit $' + st.profit.toFixed(0) + ' | Completed ' + st.res.completed + ' | Recycling ' + (st.res.pending_reuse + st.res.quarantined + st.res.unusable);
}
function planHtml(rec) {
  const p = P[rec];
  if (!p) return '<div>' + esc(rec) + ': no record details in this run payload or the recycling queue.</div>';
  let h = '<div style="border-top:1px solid #234;margin-top:4px;padding-top:4px"><b>' + esc(p.record_id) + '</b> · design ' + esc(p.design_id) +
    ' · ' + esc(p.niche || '?') + ' on ' + esc(p.product || '?') + '<br>Image: <code>' + esc(p.image_uri) + '</code> (' + esc(p.pixels) + ')' +
    '<br>Why unused: rejected by ' + esc(p.rejected_by || '?') + (p.stage ? ' at ' + esc(p.stage) : '') + ' — ' + esc(p.reason) +
    '<br>Review status at run: ' + esc(p.status_at_run || '?') + ' · ' + (p.current_status ? 'current queue status: ' + esc(p.current_status) : 'not in the current recycling queue file') + '<br>';
  const a = p.analysis;
  if (!a) return h + '<i>Not analyzed yet — open the ♻️ Recycling page (sidebar) to run the recycler analysis.</i></div>';
  h += 'Plan by <b>' + esc(a.recycler_id || '?') + '</b> · ' + esc(a.method || '?') + ' · pixels inspected: ' + (a.image_inspected ? 'yes' : 'no') + ' · source: ' + esc(p.analysis_source) + '<ul>';
  (a.suggestions || []).forEach(s => {
    h += '<li><b>' + esc(s.type) + '</b>' + (s.target_niche || s.target_product ? ' → ' + esc((s.target_niche || '-') + ' / ' + (s.target_product || '-')) : '') +
      (s.confidence !== null ? ' · confidence ' + esc(s.confidence) : '') + ' — ' + esc((s.reasons || []).join('; ')) +
      ' <span style="color:#8fa3c7">[' + esc((s.references || []).join(', ')) + ']</span></li>';
  });
  return h + '</ul><span style="color:#8fa3c7">' + esc(a.limitations) + '</span></div>';
}
function recyclingHtml() {
  const recs = st.D.filter(d => d.recycle_record);
  let h = '<br><b>Recycler plans for this run</b> (' + st.plansDone.length + '/' + recs.length + ' reviewed in this replay). Open the ♻️ <b>Recycling</b> page in the sidebar to preview images, re-analyse or decide (reuse / archive / unusable).';
  if (!recs.length) h += '<br><i>No rejected images from this run were delivered to the facility.</i>';
  recs.forEach(d => { h += (st.plansDone.some(p => p.design === d.id) ? '' : '<div style="color:#8fa3c7">awaiting replay: ' + esc(d.id) + '</div>') + planHtml(d.recycle_record); });
  if (CFG.otherQueue) h += '<div style="color:#8fa3c7;margin-top:4px">' + esc(CFG.otherQueue) + ' other record(s) in the recycling queue come from other runs or live work and are not part of this run (see the Recycling page).</div>';
  return h;
}
function renderInfo() {
  const el = document.getElementById('info');
  if (!sel) return;
  if (sel.k === 'a') {
    const a = st.agents.find(x => x.id === sel.id); if (!a) return;
    let h = '<b>' + esc(a.id) + '</b>' + (a.synthetic ? ' (arena placeholder: no recorded team worker for this room)' : '') + ' — home: ' + esc(a.home) + ' | now in: ' + esc(name(a.room)) +
      '<br>State: ' + esc(a.state.toUpperCase()) + (a.task ? ' — ' + esc(a.task) : '') + (a.job ? ' ' + Math.round(a.job.prog * 100) + '%' : '') +
      '<br>Last: ' + esc(a.lastTask || '—') + '<br>Worked: ' + a.worked + ' | Handoffs delivered: ' + a.delivered + ' | Transfers replayed: ' + a.moves + ' | Distance: ' + Math.round(a.dist) + 'px';
    if (a.room === RECYCLE || a.home === RECYCLE) {
      const cur = a.job ? a.job.d : null, mine = st.plansDone.filter(p => p.by === a.id);
      h += '<br><b>Recycler</b>: ' + (cur ? 'reviewing ' + esc(cur.id) + planHtml(cur.recycle_record) : 'no review in progress');
      if (mine.length) h += '<br>Reviewed: ' + mine.map(p => esc(p.design + ' → ' + p.text)).join(' | ');
    }
    el.innerHTML = h;
  } else if (sel.k === 'c') {
    const cy = st.cy, V = CFG.cypher.visits;
    el.innerHTML = '<b>🧪 ' + esc(CFG.cypher.name) + '</b> — manager character | mood: ' + esc(CFG.cypher.mood) + ' | at: ' + esc(name(cy.room)) + ' | ' + esc(BASIS[CFG.cypher.basis]) +
      '<br>Visits: ' + cy.visited + ' done, ' + cy.skipped + ' skipped of ' + V.length + ' · patrols: ' + cy.patrols + ' · ' + esc(cy.purpose) +
      '<br>' + (cy.kind === 'patrol' ? 'Observed (replay)' : 'Line') + ': “' + esc(cy.line) + '”' + (cy.feedback ? '<br>Observed in replay: ' + esc(cy.feedback) : '') +
      '<ul>' + cy.log.slice(-8).reverse().map(e => '<li>[' + e.t.toFixed(1) + 's] ' + esc(e.kind) + ': ' + esc(e.text) + '</li>').join('') + '</ul>';
  } else {
    const sn = st.rooms[sel.key], r = BY[sel.key];
    let h = '<b>' + esc(r.icon + ' ' + r.name.toUpperCase()) + '</b> — ' + esc(r.desc) + '<br>Status: ' + status(sel.key) + ' | Done: ' + sn.processed + '/' + sn.expected +
      ' | Queue: ' + esc(sn.queue.map(d => d.id).join(', ') || '—') + ' | Staff: ' + esc(staff(sel.key).map(a => a.id).join(', ') || '—') +
      '<br>Working: ' + (sn.jobs.length ? esc(sn.jobs.map(j => j.ag.id + ' on ' + j.d.id + ' (' + j.d.niche + ') ' + Math.round(j.prog * 100) + '%' + (j.covering ? ' covering for ' + j.covering : '')).join(' | ')) : '—');
    if (sel.key === RECYCLE) h += recyclingHtml();
    el.innerHTML = h;
  }
}
function renderRoster() {
  const el = document.getElementById('roster');
  el.innerHTML = st.agents.map(a => '<span data-id="' + esc(a.id) + '" title="click to inspect">' + esc(a.id) + ' · ' + esc(BY[a.room] ? BY[a.room].icon : '?') + ' ' +
    esc(a.state) + (a.task ? ': ' + esc(a.task) : '') + (a.job ? ' ' + Math.round(a.job.prog * 100) + '%' : '') + '</span>').join('');
}
document.getElementById('roster').addEventListener('click', e => { const id = e.target.getAttribute && e.target.getAttribute('data-id'); if (id) { sel = {k: 'a', id}; renderInfo(); } });
cv.addEventListener('click', e => {
  const r = cv.getBoundingClientRect(), x = (e.clientX - r.left) * CFG.w / r.width, y = (e.clientY - r.top) * CFG.h / r.height;
  sel = null;
  if (Math.hypot(st.cy.x - x, st.cy.y - y) < 24) sel = {k: 'c'};
  if (!sel) st.agents.forEach(a => { if (Math.hypot(a.x - x, a.y - y) < 18) sel = {k: 'a', id: a.id}; });
  if (!sel) ROOMS.forEach(rm => { if (x >= rm.x && x <= rm.x + rm.w && y >= rm.y && y <= rm.y + rm.h) sel = {k: 's', key: rm.key}; });
  if (!sel) document.getElementById('info').textContent = 'Click an agent, Dr. Cypher or a room (try the ♻️ Recycling Facility) to inspect it.';
  renderInfo();
});
const setSpeed = v => { speed = Math.max(0.5, Math.min(8, v)); document.getElementById('speed').textContent = 'SPEED x' + speed; };
document.getElementById('play').onclick = e => { playing = !playing; e.target.textContent = playing ? '⏸ PAUSE' : '▶ PLAY'; };
document.getElementById('slow').onclick = () => setSpeed(speed / 2);
document.getElementById('fast').onclick = () => setSpeed(speed * 2);
document.getElementById('reset').onclick = () => { reset(); renderInfo(); };
function step(dt) { const steps = Math.max(1, Math.ceil(speed)); for (let k = 0; k < steps; k++) update(dt * speed / steps); }
function loop(now) {
  const dt = Math.min((now - last) / 1000, 0.1); last = now;
  if (playing) step(dt);
  draw(); infoT -= dt;
  if (infoT <= 0) { infoT = 0.25; renderInfo(); renderRoster(); }
  requestAnimationFrame(loop);
}
// Inspection hook for automated browser tests (advances the same update() loop).
window.arenaDebug = {
  advance(seconds, dt) { dt = dt || 0.05; for (let t = 0; t < seconds; t += dt) update(dt); draw(); renderInfo(); renderRoster(); },
  select(s) { sel = s; renderInfo(); },
  summary() {
    return {t: st.t, total: st.D.length, spawned: st.spawned, resolved: st.resolved, res: Object.assign({}, st.res), finished: finishAll(), handoffs: st.handoffs,
      agents: st.agents.map(a => ({id: a.id, room: a.room, state: a.state, worked: a.worked, delivered: a.delivered, moves: a.moves, synthetic: a.synthetic})),
      rooms: Object.fromEntries(Object.entries(st.rooms).map(([k, v]) => [k, {processed: v.processed, expected: v.expected, queue: v.queue.length, jobs: v.jobs.length}])),
      cypher: {room: st.cy.room, state: st.cy.state, x: st.cy.x, y: st.cy.y, vi: st.cy.vi, visited: st.cy.visited, skipped: st.cy.skipped, patrols: st.cy.patrols, home: st.cy.homeLogged,
        log: st.cy.log.map(e => e.kind + ': ' + e.text)},
      plans: st.plansDone.slice(), trails: st.D.map(d => ({id: d.id, trail: d.trail.slice(), done: d.done, resolution: d.resolution})), transfers: st.xferLog.slice()};
  },
};
reset(); requestAnimationFrame(loop);
</script>
"""
