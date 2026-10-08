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


def design_payload(df, limit=40, recycling=None):
    """Reduce a merged designs/results frame to the records the arena animates.

    ``recycling`` is the run payload's ``recycling`` section (absent in older
    runs); rejected designs with a recycling record are carried to the
    Recycling Facility, everything else keeps the old behaviour."""
    by_design = {}
    for record in (recycling or {}).get("records", []) or []:
        if isinstance(record, dict) and record.get("source_design_id"):
            by_design[str(record["source_design_id"])] = record
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
        rows.append({
            "id": design_id,
            "niche": str(r["niche"]),
            "flagged": bool(r["compliance_status"] == "flagged"),
            "approved": approved,
            "profit": float(r["profit"]) if r["profit"] == r["profit"] else 0.0,
            "has_image": has_image,
            "recycle_status": status,
            "recycle_record": str(record.get("record_id")) if record else None,
            "outcome": outcome,
        })
    return rows


def arena_agents(team_report=None):
    """Agents with stable IDs placed in their department's room at the
    *start* of the run (recorded transfers are then replayed)."""
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
    for room, agent_id in SYNTHETIC_STAFF.items():
        if room not in staffed and agent_id not in agents:
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


def build_arena_html(designs, team=None, character=None, run_label=""):
    """``team`` is the run's team report and ``character`` Dr. Cypher's
    ``to_dict()``; both are optional so older runs still render."""
    rooms = room_index()
    character = character or {}
    config = {
        "stations": station_layout(),
        "facilities": facility_layout(),
        "rooms": {k: {"key": k, "home": v["home"], "exit": v["exit"]} for k, v in rooms.items()},
        "command": COMMAND,
        "ops": OPS_BOARD,
        "hud": HUD,
        "designs": designs,
        "agents": arena_agents(team),
        "transfers": arena_transfers(team),
        "offsite": sorted({a for a, info in agents_for(team).items()
                           if ROOM_FOR_DEPARTMENT.get(info.get("current_department")) is None}),
        "cypher": {
            "name": str(character.get("display_name") or "Dr. Cypher"),
            "mood": str(character.get("mood") or "focused"),
            "line": str(character.get("line") or ""),
            "visits": [{"room": ROOM_FOR_DEPARTMENT.get(v.get("department")), "purpose": str(v.get("purpose", "")),
                        "line": str(v.get("line", ""))}
                       for v in character.get("visits", []) or [] if isinstance(v, dict)],
        },
        "label": str(run_label or "recorded run"),
        "w": CANVAS_W, "h": CANVAS_H, "corridorY": CORRIDOR_Y, "lowerY": LOWER_CORRIDOR_Y, "shaftX": SHAFT_X,
    }
    return ARENA_TEMPLATE.replace("__CONFIG__", _json_for_script(config))


ARENA_TEMPLATE = r"""
<div style="background:#0a0e27;color:#00ff41;font-family:'Courier New',monospace;">
<div id="bar" style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;padding:6px 0;">
  <button id="play">⏸ PAUSE</button><button id="slow">⏪ SLOWER</button><button id="fast">⏩ FASTER</button>
  <button id="reset">🔄 RESTART</button><span id="speed" style="color:#00ccff">SPEED x1</span>
  <span id="replay" style="color:#ff6b9d"></span>
  <span id="metrics" style="margin-left:auto;color:#ffaa00"></span>
</div>
<canvas id="c" style="width:100%;border:2px solid #00ff41;border-radius:8px;box-shadow:0 0 20px rgba(0,255,65,.4);cursor:pointer"></canvas>
<div id="info" style="margin-top:6px;border:2px solid #00ccff;border-radius:8px;padding:10px;color:#00ccff;min-height:48px">
Click an agent, Dr. Cypher or a room to inspect it.</div>
</div>
<style>#bar button{background:linear-gradient(135deg,#00ff41,#00cc33);color:#0a0e27;border:0;border-radius:6px;padding:6px 12px;font-weight:bold;font-family:inherit;cursor:pointer}</style>
<script>
const CFG = __CONFIG__;
const S = CFG.stations, F = CFG.facilities, D = CFG.designs, R = CFG.rooms;
const ROOMS = S.concat(F), BY = {};
ROOMS.forEach(r => BY[r.key] = r);
const FINAL = 'simulator', RECYCLE = 'recycling';
const cv = document.getElementById('c'), ctx = cv.getContext('2d');
cv.width = CFG.w; cv.height = CFG.h;
const WALK = 140, DUR = 1.4, SPAWN = 1.2, TALK = 3.0;
let speed = 1, playing = true, sel = null, st, last = performance.now();
document.getElementById('replay').textContent = 'REPLAY of ' + CFG.label + ' (recorded events, not live work)';

function esc(v) { return String(v).replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c])); }
function route(a, b) {
  if (a === b) return [R[a].home.slice()];
  const pts = R[a].exit.concat(R[b].exit.slice().reverse()), out = [];
  pts.forEach(p => { const l = out[out.length - 1]; if (!l || l[0] !== p[0] || l[1] !== p[1]) out.push(p.slice()); });
  return out;
}
function nextKey(key) { const i = S.findIndex(s => s.key === key); return i >= 0 && i < S.length - 1 ? S[i + 1].key : null; }
function slot(ag) {
  if (!ag.room || !R[ag.room]) return null;
  const mates = st.agents.filter(a => a.room === ag.room), k = mates.indexOf(ag), h = R[ag.room].home;
  return [h[0] + (k - (mates.length - 1) / 2) * 46, h[1]];
}
function reset() {
  st = {t: 0, spawnT: 0, next: 0, spawned: 0, done: 0, held: 0, reuse: 0, quarantined: 0, unusable: 0, noImage: 0, profit: 0, fx: [], arrivals: 0,
    rooms: {}, xfer: CFG.transfers.map(e => Object.assign({fired: false}, e)), xferLog: []};
  ROOMS.forEach(r => st.rooms[r.key] = {queue: [], cur: null, prog: 0, processed: 0, worker: null});
  st.agents = CFG.agents.filter(a => a.room).map(a => ({id: a.id, home: a.home_department, room: a.room, synthetic: a.synthetic, x: 0, y: 0, state: 'idle', pkg: null, wp: [], dest: null, delivered: 0, worked: 0, dist: 0, moves: 0}));
  st.agents.forEach(a => { const p = slot(a); a.x = p[0]; a.y = p[1]; });
  const ch = R.command.home;
  st.cy = {x: ch[0], y: ch[1], room: 'command', vi: 0, state: 'idle', wp: [], talk: 0, line: CFG.cypher.line, purpose: 'At the command center'};
}
function resolved() { return st.done + st.held + st.reuse + st.quarantined + st.unusable + st.noImage; }
function finishAll() { return resolved() >= D.length && st.agents.every(a => a.state === 'idle'); }
function fx(x, y, txt, c) { st.fx.push({x, y, t: 0, txt, c}); }
function present(key) { return st.agents.filter(a => a.room === key && a.state === 'idle' && Math.hypot(a.x - slot(a)[0], a.y - slot(a)[1]) < 1); }
function walk(ag, pts) { ag.wp = pts; }
function dispatch(ag, d, from, to) {
  ag.pkg = d; ag.state = 'deliver'; ag.dest = to; walk(ag, route(from, to).slice(1));
}
function finish(key, ag, d) {
  const r = BY[key], hx = r.home[0], hy = r.home[1] - 46;
  const rejected = (key === 'compliance' && d.flagged) || (key === 'approval' && !d.approved);
  if (rejected) {
    if (d.recycle_status && d.has_image) { fx(hx, hy, '♻ to recycling', '#ffaa00'); dispatch(ag, d, key, RECYCLE); }
    else if (key === 'approval' && !d.flagged) { st.held++; fx(hx, hy, 'HOLD', '#ffaa00'); }
    else { st.noImage++; fx(hx, hy, '✖', '#ff4444'); }
  } else if (key === FINAL) { st.done++; st.profit += d.profit; fx(hx, hy, '+$' + d.profit.toFixed(0), '#00ff41'); }
  else if (key === RECYCLE) {
    if (d.outcome === 'quarantined') { st.quarantined++; fx(hx, hy, '☣ QUARANTINE', '#ff4444'); }
    else if (d.outcome === 'pending_reuse') { st.reuse++; fx(hx, hy, '♻ PENDING REUSE', '#00ff41'); }
    else { st.unusable++; fx(hx, hy, '🗄 UNUSABLE', '#8a8a8a'); }
  } else { dispatch(ag, d, key, nextKey(key)); }
}
function fireTransfers() {
  st.xfer.forEach(e => {
    if (e.fired) return;
    const due = e.initiated_by === 'auto:demand' ? st.arrivals > 0 : e.initiated_by === 'auto:end_of_shift' ? resolved() >= D.length : st.t > 1;
    const ag = st.agents.find(a => a.id === e.agent_id);
    if (!due || !ag || ag.state !== 'idle' || !e.to) return;
    e.fired = true;
    const from = ag.room; ag.room = e.to; ag.moves++; ag.state = 'transfer';
    walk(ag, route(from, e.to).slice(1).concat([slot(ag)]));
    st.xferLog.push(ag.id + ': ' + from + ' → ' + e.to + ' (' + e.initiated_by + ')');
    fx(ag.x, ag.y - 30, '🚶 transfer', '#ff6b9d');
  });
}
function roomActive(key) { const sn = st.rooms[key]; return sn && (sn.processed > 0 || sn.cur || sn.queue.length); }
function cypherTick() {
  const cy = st.cy, V = CFG.cypher.visits;
  if (cy.state !== 'idle') return;
  if (cy.vi < V.length) {
    const v = V[cy.vi];
    if (!v.room || !R[v.room]) { cy.vi++; return; }
    if (!roomActive(v.room)) return;
    cy.target = v; cy.state = 'walk';
    cy.wp = route(cy.room, v.room).slice(1); const last = cy.wp[cy.wp.length - 1]; last[1] -= 44; cy.room = v.room;
  } else if (cy.room !== 'command' && resolved() >= D.length) {
    cy.target = null; cy.state = 'walk'; cy.wp = route(cy.room, 'command').slice(1); cy.room = 'command';
  }
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
function update(dt) {
  st.t += dt; st.spawnT += dt;
  if (st.next < D.length && st.spawnT >= SPAWN) { st.spawnT = 0; st.rooms[S[0].key].queue.push(D[st.next++]); st.spawned++; }
  fireTransfers();
  ROOMS.forEach(r => {
    const sn = st.rooms[r.key];
    if (!sn.cur && sn.queue.length) {
      const free = present(r.key);
      if (free.length) { sn.cur = sn.queue.shift(); sn.prog = 0; sn.worker = free[0]; free[0].state = 'work'; }
    }
    if (sn.cur) {
      sn.prog += dt / DUR;
      if (sn.prog >= 1) {
        const d = sn.cur, ag = sn.worker; sn.cur = null; sn.worker = null; sn.processed++; ag.state = 'idle'; ag.worked++;
        finish(r.key, ag, d);
      }
    }
  });
  st.agents.forEach(ag => {
    if (ag.state === 'idle' || ag.state === 'work') return;
    if (!move(ag, dt)) return;
    if (ag.state === 'deliver') {
      st.rooms[ag.dest].queue.push(ag.pkg); if (ag.dest === RECYCLE) st.arrivals++;
      ag.pkg = null; ag.delivered++; fx(ag.x, ag.y - 30, '📨', '#00ccff');
      ag.state = 'return'; walk(ag, route(ag.dest, ag.room).slice(1).concat([slot(ag)]));
    } else { ag.state = 'idle'; const p = slot(ag); ag.x = p[0]; ag.y = p[1]; }
  });
  st.agents.forEach(ag => { if (ag.state === 'idle') { const p = slot(ag); ag.x = p[0]; ag.y = p[1]; } });
  const cy = st.cy;
  if (cy.state === 'walk' && move(cy, dt)) {
    if (cy.target) { cy.state = 'talk'; cy.talk = TALK; cy.line = cy.target.line; cy.purpose = cy.target.purpose; }
    else { cy.state = 'idle'; cy.line = CFG.cypher.line; cy.purpose = 'Back at the command center'; }
  } else if (cy.state === 'talk') { cy.talk -= dt; if (cy.talk <= 0) { cy.state = 'idle'; cy.vi++; } }
  cypherTick();
  st.fx.forEach(f => f.t += dt); st.fx = st.fx.filter(f => f.t < 1.4);
}
function status(key) {
  const sn = st.rooms[key];
  if (sn.cur) return 'BUSY';
  if (sn.queue.length) return present(key).length ? 'BUSY' : 'WAITING FOR WORKER';
  return finishAll() ? 'COMPLETE' : 'IDLE';
}
const COL = {BUSY: '#ffaa00', IDLE: '#4a5a7a', COMPLETE: '#00ff41', 'WAITING FOR WORKER': '#00ccff'};
function glowRect(x, y, w, h, c) { ctx.shadowColor = c; ctx.shadowBlur = 12; ctx.strokeStyle = c; ctx.lineWidth = 2; ctx.strokeRect(x, y, w, h); ctx.shadowBlur = 0; }
function clip(t, n) { t = String(t); return t.length > n ? t.slice(0, n - 1) + '…' : t; }
function drawCommand() {
  const c = CFG.command;
  ctx.fillStyle = '#12183a'; ctx.fillRect(c.x, c.y, c.w, c.h); glowRect(c.x, c.y, c.w, c.h, '#ff6b9d');
  ctx.fillStyle = '#ff6b9d'; ctx.font = 'bold 13px Courier New'; ctx.fillText('🧪 COMMAND CENTER', 36, 26);
  ctx.fillStyle = '#00ccff'; ctx.font = '11px Courier New'; ctx.fillText(clip(CFG.cypher.name + ' · mood: ' + CFG.cypher.mood, 36), 36, 44);
  ctx.fillStyle = '#00ff41'; ctx.font = '12px Courier New'; ctx.fillText(clip('"' + st.cy.line + '"', 52), 504, 30);
  ctx.fillStyle = '#8fa3c7'; ctx.font = '10px Courier New'; ctx.fillText(clip(st.cy.purpose, 62), 504, 47);
}
function drawCypher() {
  const cy = st.cy, x = cy.x, y = cy.y + (cy.state === 'walk' ? Math.sin(st.t * 12) * 2 : 0);
  ctx.fillStyle = '#e8f7ff'; ctx.fillRect(x - 9, y + 2, 18, 16);
  ctx.fillStyle = '#ffd9b3'; ctx.beginPath(); ctx.arc(x, y - 6, 9, 0, 7); ctx.fill();
  ctx.fillStyle = '#4da6ff';
  for (let k = -2; k <= 2; k++) { ctx.beginPath(); ctx.moveTo(x + k * 4 - 3, y - 12); ctx.lineTo(x + k * 4, y - 22 - (k % 2 ? 0 : 3)); ctx.lineTo(x + k * 4 + 3, y - 12); ctx.fill(); }
  ctx.strokeStyle = sel && sel.k === 'c' ? '#fff' : '#ff6b9d'; ctx.lineWidth = 2; ctx.beginPath(); ctx.arc(x, y, 22, 0, 7); ctx.stroke();
  ctx.font = 'bold 9px Courier New'; ctx.textAlign = 'center'; ctx.fillStyle = '#ff6b9d'; ctx.fillText('DR. CYPHER', x, y + 32); ctx.textAlign = 'left';
  if (cy.state === 'talk') {
    const t = clip(cy.line, 44), w = ctx.measureText(t).width + 16, bx = Math.min(Math.max(20, x - w / 2), CFG.w - 20 - w);
    ctx.fillStyle = 'rgba(18,24,58,.95)'; ctx.fillRect(bx, y - 52, w, 20); glowRect(bx, y - 52, w, 20, '#ff6b9d');
    ctx.fillStyle = '#ffffff'; ctx.font = '11px Courier New'; ctx.fillText(t, bx + 8, y - 38);
  }
}
function drawRoom(r) {
  const sn = st.rooms[r.key], stt = status(r.key), c = COL[stt], fac = r.key === RECYCLE;
  ctx.fillStyle = fac ? '#132a1f' : '#0f1535'; ctx.fillRect(r.x, r.y, r.w, r.h); glowRect(r.x, r.y, r.w, r.h, sel && sel.k === 's' && sel.key === r.key ? '#ffffff' : c);
  ctx.fillStyle = fac ? '#7dff9b' : '#00ccff'; ctx.font = 'bold 13px Courier New'; ctx.fillText(r.icon + ' ' + r.name, r.x + 8, r.y + 20);
  ctx.fillStyle = c; ctx.font = '11px Courier New'; ctx.fillText('● ' + stt, r.x + 8, r.y + 36);
  ctx.fillStyle = '#ffaa00'; ctx.fillText('queue: ' + sn.queue.length + '  done: ' + sn.processed + '  staff: ' + st.agents.filter(a => a.room === r.key).length, r.x + 8, r.y + 52);
  ctx.fillStyle = '#0a0e27'; ctx.fillRect(r.x + 8, r.y + 60, r.w - 16, 8);
  ctx.fillStyle = '#00ff41'; ctx.fillRect(r.x + 8, r.y + 60, (r.w - 16) * (sn.cur ? Math.min(sn.prog, 1) : 0), 8);
}
function drawOps() {
  const o = CFG.ops;
  ctx.fillStyle = '#12183a'; ctx.fillRect(o.x, o.y, o.w, o.h); glowRect(o.x, o.y, o.w, o.h, '#00ccff');
  ctx.fillStyle = '#00ccff'; ctx.font = 'bold 12px Courier New'; ctx.fillText('📋 OPS BOARD (this run)', o.x + 10, o.y + 20);
  ctx.font = '11px Courier New';
  const lines = [['✔ completed', st.done, '#00ff41'], ['⏸ held for human review', st.held, '#ffaa00'], ['♻ pending reuse review', st.reuse, '#7dff9b'],
    ['☣ quarantined', st.quarantined, '#ff4444'], ['🗄 unusable / archived', st.unusable, '#8a8a8a'], ['✖ rejected (no record)', st.noImage, '#ff8888']];
  lines.forEach((l, i) => { ctx.fillStyle = l[2]; ctx.fillText(l[0] + ': ' + l[1], o.x + 10 + (i % 2) * 215, o.y + 42 + Math.floor(i / 2) * 18); });
  ctx.fillStyle = '#ff6b9d'; ctx.fillText(clip('Transfers: ' + (st.xferLog.length ? st.xferLog.join(' | ') : 'none recorded yet'), 58), o.x + 10, o.y + 106);
  if (CFG.offsite.length) { ctx.fillStyle = '#8fa3c7'; ctx.fillText(clip('No arena room: ' + CFG.offsite.join(', '), 58), o.x + 10, o.y + 124); }
}
function pkg(x, y) { ctx.shadowColor = '#00ccff'; ctx.shadowBlur = 10; ctx.fillStyle = '#00ccff'; ctx.fillRect(x - 5, y - 5, 10, 10); ctx.shadowBlur = 0; }
function draw() {
  ctx.fillStyle = '#0a0e27'; ctx.fillRect(0, 0, CFG.w, CFG.h);
  ctx.fillStyle = '#141a40'; ctx.fillRect(20, CFG.corridorY - 30, 920, 60); ctx.fillRect(20, CFG.lowerY - 25, 920, 50); ctx.fillRect(CFG.shaftX - 10, 58, 20, CFG.lowerY - 58);
  ctx.strokeStyle = 'rgba(0,255,65,.25)'; ctx.setLineDash([8, 8]); ctx.beginPath();
  ctx.moveTo(20, CFG.corridorY); ctx.lineTo(940, CFG.corridorY); ctx.moveTo(20, CFG.lowerY); ctx.lineTo(940, CFG.lowerY); ctx.moveTo(CFG.shaftX, 58); ctx.lineTo(CFG.shaftX, CFG.lowerY); ctx.stroke(); ctx.setLineDash([]);
  drawCommand(); ROOMS.forEach(drawRoom); drawOps();
  ROOMS.forEach(r => { if (st.rooms[r.key].cur) pkg(r.x + r.w - 20, r.y + 22 + Math.sin(st.t * 6) * 2); });
  st.agents.forEach(a => {
    const room = BY[a.room] || BY[S[0].key], bob = a.state === 'idle' || a.state === 'work' ? 0 : Math.sin(st.t * 14) * 3, away = a.room !== a.home;
    ctx.shadowColor = away ? '#ff6b9d' : '#00ff41'; ctx.shadowBlur = 12; ctx.fillStyle = '#1a2d4e'; ctx.strokeStyle = sel && sel.k === 'a' && sel.id === a.id ? '#fff' : (away ? '#ff6b9d' : '#00ff41'); ctx.lineWidth = 2;
    ctx.beginPath(); ctx.arc(a.x, a.y + bob, 15, 0, 7); ctx.fill(); ctx.stroke(); ctx.shadowBlur = 0;
    ctx.font = '15px serif'; ctx.textAlign = 'center'; ctx.fillStyle = '#fff'; ctx.fillText((BY[a.home] || room).icon, a.x, a.y + bob + 5);
    ctx.font = '9px Courier New'; ctx.fillStyle = away ? '#ff6b9d' : '#00ff41'; ctx.fillText(clip(a.id, 14), a.x, a.y + bob + 27);
    if (a.pkg) pkg(a.x + 14, a.y + bob - 14);
    ctx.textAlign = 'left';
  });
  drawCypher();
  st.fx.forEach(f => { ctx.globalAlpha = Math.max(0, 1 - f.t / 1.4); ctx.fillStyle = f.c; ctx.font = 'bold 13px Courier New'; ctx.fillText(f.txt, f.x - 20, f.y - f.t * 30); ctx.globalAlpha = 1; });
  const h = CFG.hud;
  ctx.fillStyle = '#12183a'; ctx.fillRect(h.x, h.y, h.w, h.h); glowRect(h.x, h.y, h.w, h.h, '#00ccff');
  ctx.fillStyle = '#00ccff'; ctx.font = '12px Courier New';
  ctx.fillText('FLOW: ' + st.spawned + '/' + D.length + ' entered → ' + st.done + ' completed | ' + st.held + ' held | ' + st.reuse + ' pending reuse | ' + st.quarantined + ' quarantined | ' + (st.unusable + st.noImage) + ' unusable | ' + (finishAll() ? 'ALL DESIGNS RESOLVED' : 'IN PROGRESS'), h.x + 12, h.y + 25);
  document.getElementById('metrics').textContent = 'Profit $' + st.profit.toFixed(0) + ' | Completed ' + st.done + ' | Recycling ' + (st.reuse + st.quarantined + st.unusable);
  renderInfo();
}
function renderInfo() {
  const el = document.getElementById('info');
  if (!sel) return;
  if (sel.k === 'a') {
    const a = st.agents.find(x => x.id === sel.id); if (!a) return;
    el.innerHTML = '<b>' + esc(a.id) + '</b>' + (a.synthetic ? ' (arena placeholder, not a team worker)' : '') + ' — home: ' + esc(a.home) + ' | now in: ' + esc(a.room) + '<br>State: ' + esc(a.state.toUpperCase()) + ' | Worked: ' + a.worked + ' | Deliveries: ' + a.delivered + ' | Transfers replayed: ' + a.moves + ' | Distance: ' + Math.round(a.dist) + 'px' + (a.pkg ? ' | Carrying: ' + esc(a.pkg.id) : '');
  } else if (sel.k === 'c') {
    const cy = st.cy;
    el.innerHTML = '<b>🧪 ' + esc(CFG.cypher.name) + '</b> — manager character | mood: ' + esc(CFG.cypher.mood) + ' | at: ' + esc(cy.room) + ' | visit ' + Math.min(cy.vi + 1, CFG.cypher.visits.length) + '/' + CFG.cypher.visits.length + '<br>' + esc(cy.purpose) + ' — “' + esc(cy.line) + '”';
  } else {
    const sn = st.rooms[sel.key], r = BY[sel.key];
    el.innerHTML = '<b>' + esc(r.icon + ' ' + r.name.toUpperCase()) + '</b> — ' + esc(r.desc) + '<br>Status: ' + status(sel.key) + ' | Queue: ' + sn.queue.length + ' | Processed: ' + sn.processed + ' | Staff: ' + esc(st.agents.filter(a => a.room === sel.key).map(a => a.id).join(', ') || '—') + ' | Current: ' + (sn.cur ? esc(sn.cur.id + ' (' + sn.cur.niche + ')') + ' ' + Math.round(sn.prog * 100) + '%' : '—');
  }
}
cv.addEventListener('click', e => {
  const r = cv.getBoundingClientRect(), x = (e.clientX - r.left) * CFG.w / r.width, y = (e.clientY - r.top) * CFG.h / r.height;
  sel = null;
  if (Math.hypot(st.cy.x - x, st.cy.y - y) < 24) sel = {k: 'c'};
  if (!sel) st.agents.forEach(a => { if (Math.hypot(a.x - x, a.y - y) < 18) sel = {k: 'a', id: a.id}; });
  if (!sel) ROOMS.forEach(rm => { if (x >= rm.x && x <= rm.x + rm.w && y >= rm.y && y <= rm.y + rm.h) sel = {k: 's', key: rm.key}; });
  if (!sel) document.getElementById('info').textContent = 'Click an agent, Dr. Cypher or a room to inspect it.';
});
const setSpeed = v => { speed = Math.max(0.5, Math.min(8, v)); document.getElementById('speed').textContent = 'SPEED x' + speed; };
document.getElementById('play').onclick = e => { playing = !playing; e.target.textContent = playing ? '⏸ PAUSE' : '▶ PLAY'; };
document.getElementById('slow').onclick = () => setSpeed(speed / 2);
document.getElementById('fast').onclick = () => setSpeed(speed * 2);
document.getElementById('reset').onclick = () => reset();
function loop(now) {
  const dt = Math.min((now - last) / 1000, 0.1); last = now;
  if (playing) { const steps = Math.max(1, Math.ceil(speed)); for (let k = 0; k < steps; k++) update(dt * speed / steps); }
  draw(); requestAnimationFrame(loop);
}
reset(); requestAnimationFrame(loop);
</script>
"""
