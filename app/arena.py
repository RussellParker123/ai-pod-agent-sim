"""Fallout Shelter-style simulation arena: layout data + self-contained canvas renderer."""
import json

STATIONS = [
    {"key": "trend", "agent": "TREND", "icon": "🎯", "name": "Trend Lab", "desc": "finds trending niches"},
    {"key": "prompt", "agent": "PROMPT", "icon": "📝", "name": "Prompt Workshop", "desc": "writes prompts"},
    {"key": "image", "agent": "IMAGE", "icon": "🎨", "name": "Image Studio", "desc": "generates images"},
    {"key": "compliance", "agent": "COMPLIANCE", "icon": "🛡️", "name": "Compliance Office", "desc": "checks violations"},
    {"key": "mockup", "agent": "MOCKUP", "icon": "📦", "name": "Mockup Assembly", "desc": "selects products"},
    {"key": "pricing", "agent": "PRICING", "icon": "💰", "name": "Pricing Bureau", "desc": "sets prices"},
    {"key": "approval", "agent": "APPROVAL", "icon": "✅", "name": "Approval Gate", "desc": "approves designs"},
    {"key": "simulator", "agent": "SIMULATOR", "icon": "📊", "name": "Market Simulator", "desc": "calculates results"},
]

COLUMNS = 4
ROOM_W, ROOM_H = 220, 150
CORRIDOR_Y = 280
TOP_ROW_Y, BOTTOM_ROW_Y = 70, 340
CANVAS_W, CANVAS_H = 960, 560


def station_layout():
    """Return room geometry for each station (grid of rooms around a central corridor)."""
    layout = []
    for i, s in enumerate(STATIONS):
        col, row = i % COLUMNS, i // COLUMNS
        x = 20 + col * (ROOM_W + 20)
        y = TOP_ROW_Y if row == 0 else BOTTOM_ROW_Y
        layout.append({**s, "index": i, "x": x, "y": y, "w": ROOM_W, "h": ROOM_H,
                       "door": (x + ROOM_W // 2, CORRIDOR_Y), "home": (x + ROOM_W // 2, y + ROOM_H - 40)})
    return layout


def find_path(src, dst, layout=None):
    """Waypoints for an agent walking from station src's room to station dst's room via the corridor."""
    layout = layout or station_layout()
    a, b = layout[src], layout[dst]
    if src == dst:
        return [a["home"]]
    return [a["home"], a["door"], b["door"], b["home"]]


def design_payload(df, limit=40):
    """Reduce a merged designs/results frame to the records the arena animates."""
    rows = []
    for _, r in df.head(limit).iterrows():
        rows.append({
            "id": str(r["design_id"]),
            "niche": str(r["niche"]),
            "flagged": bool(r["compliance_status"] == "flagged"),
            "approved": bool(r["approved"]),
            "profit": float(r["profit"]) if r["profit"] == r["profit"] else 0.0,
        })
    return rows


def build_arena_html(designs):
    config = {"stations": station_layout(), "designs": designs, "w": CANVAS_W, "h": CANVAS_H,
              "corridorY": CORRIDOR_Y}
    data = json.dumps(config).replace("</", "<\\/")
    return ARENA_TEMPLATE.replace("__CONFIG__", data)


ARENA_TEMPLATE = r"""
<div style="background:#0a0e27;color:#00ff41;font-family:'Courier New',monospace;">
<div id="bar" style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;padding:6px 0;">
  <button id="play">⏸ PAUSE</button><button id="slow">⏪ SLOWER</button><button id="fast">⏩ FASTER</button>
  <button id="reset">🔄 RESTART</button><span id="speed" style="color:#00ccff">SPEED x1</span>
  <span id="metrics" style="margin-left:auto;color:#ffaa00"></span>
</div>
<canvas id="c" style="width:100%;border:2px solid #00ff41;border-radius:8px;box-shadow:0 0 20px rgba(0,255,65,.4);cursor:pointer"></canvas>
<div id="info" style="margin-top:6px;border:2px solid #00ccff;border-radius:8px;padding:10px;color:#00ccff;min-height:48px">
Click an agent or a station to inspect it.</div>
</div>
<style>#bar button{background:linear-gradient(135deg,#00ff41,#00cc33);color:#0a0e27;border:0;border-radius:6px;padding:6px 12px;font-weight:bold;font-family:inherit;cursor:pointer}</style>
<script>
const CFG = __CONFIG__;
const S = CFG.stations, D = CFG.designs;
const cv = document.getElementById('c'), ctx = cv.getContext('2d');
cv.width = CFG.w; cv.height = CFG.h;
const WALK = 140, DUR = 1.4, SPAWN = 1.2;
let speed = 1, playing = true, sel = null, st, last = performance.now();

function path(a, b) {
  if (a === b) return [S[a].home];
  return [S[a].home, S[a].door, S[b].door, S[b].home];
}
function reset() {
  st = {t: 0, spawnT: 0, next: 0, spawned: 0, done: 0, rejected: 0, profit: 0, fx: [],
    stations: S.map(() => ({queue: [], cur: null, prog: 0, processed: 0, busyTime: 0})),
    agents: S.map((s, i) => ({i, x: s.home[0], y: s.home[1], state: 'idle', pkg: null, wp: [], to: i, delivered: 0, dist: 0}))};
}
function finishAll() { return st.done + st.rejected >= D.length; }
function cipherLine() {
  const dec = st.done + st.rejected;
  if (!dec) return "Hurry up, you lazy circuits. Science waits for no one.";
  const r = st.done / dec;
  if (r >= .7) return "*burp* Okay, that is actually impressive.";
  if (r >= .5) return "Acceptable. Could be better, obviously.";
  if (r >= .3) return "Meh. My toaster has better throughput.";
  return "This is a disaster! Recalibrating my disappointment...";
}
function update(dt) {
  st.t += dt;
  st.spawnT += dt;
  if (st.next < D.length && st.spawnT >= SPAWN) {
    st.spawnT = 0; st.stations[0].queue.push(D[st.next++]); st.spawned++;
  }
  S.forEach((s, i) => {
    const sn = st.stations[i], ag = st.agents[i];
    if (!sn.cur && sn.queue.length && ag.state === 'idle') { sn.cur = sn.queue.shift(); sn.prog = 0; }
    if (sn.cur) {
      sn.prog += dt / DUR; sn.busyTime += dt;
      if (sn.prog >= 1) {
        const d = sn.cur; sn.cur = null; sn.processed++;
        if ((i === 3 && d.flagged) || (i === 6 && !d.approved)) { st.rejected++; st.fx.push({x: s.home[0], y: s.home[1] - 40, t: 0, txt: '✖', c: '#ff4444'}); }
        else if (i === S.length - 1) { st.done++; st.profit += d.profit; st.fx.push({x: s.home[0], y: s.home[1] - 40, t: 0, txt: '+$' + d.profit.toFixed(0), c: '#00ff41'}); }
        else { ag.pkg = d; ag.state = 'deliver'; ag.to = i + 1; ag.wp = path(i, i + 1).slice(1); }
      }
    }
  });
  st.agents.forEach(ag => {
    if (ag.state === 'idle') return;
    let step = WALK * dt;
    while (step > 0 && ag.wp.length) {
      const [tx, ty] = ag.wp[0], dx = tx - ag.x, dy = ty - ag.y, d = Math.hypot(dx, dy);
      if (d <= step) { ag.x = tx; ag.y = ty; ag.wp.shift(); ag.dist += d; step -= d; }
      else { ag.x += dx / d * step; ag.y += dy / d * step; ag.dist += step; step = 0; }
    }
    if (!ag.wp.length) {
      if (ag.state === 'deliver') {
        st.stations[ag.to].queue.push(ag.pkg); ag.pkg = null; ag.delivered++;
        st.fx.push({x: ag.x, y: ag.y - 30, t: 0, txt: '📨', c: '#00ccff'});
        ag.state = 'return'; ag.wp = [S[ag.to].door, S[ag.i].door, S[ag.i].home];
      } else { ag.state = 'idle'; }
    }
  });
  st.fx.forEach(f => f.t += dt); st.fx = st.fx.filter(f => f.t < 1.2);
}
function status(i) {
  const sn = st.stations[i];
  if (sn.cur) return 'BUSY';
  if (sn.queue.length) return 'WAITING FOR COURIER';
  return finishAll() ? 'COMPLETE' : 'IDLE';
}
const COL = {BUSY: '#ffaa00', IDLE: '#4a5a7a', COMPLETE: '#00ff41', 'WAITING FOR COURIER': '#00ccff'};
function glowRect(x, y, w, h, c) { ctx.shadowColor = c; ctx.shadowBlur = 12; ctx.strokeStyle = c; ctx.lineWidth = 2; ctx.strokeRect(x, y, w, h); ctx.shadowBlur = 0; }
function drawCipher() {
  ctx.fillStyle = '#12183a'; ctx.fillRect(20, 6, 920, 52); glowRect(20, 6, 920, 52, '#ff6b9d');
  ctx.fillStyle = '#4da6ff';
  for (let k = 0; k < 5; k++) { ctx.beginPath(); ctx.moveTo(48 + k * 9, 24); ctx.lineTo(52 + k * 9, 6 + (k % 2) * 4); ctx.lineTo(58 + k * 9, 24); ctx.fill(); }
  ctx.fillStyle = '#ffd9b3'; ctx.beginPath(); ctx.arc(70, 32, 14, 0, 7); ctx.fill();
  ctx.fillStyle = '#e8f7ff'; ctx.fillRect(52, 44, 36, 14);
  ctx.fillStyle = '#ff6b9d'; ctx.font = 'bold 13px Courier New'; ctx.fillText('DR. CIPHER — COMMAND CENTER', 100, 24);
  ctx.fillStyle = '#00ff41'; ctx.font = '12px Courier New'; ctx.fillText('"' + cipherLine() + '"', 100, 44);
}
function drawRoom(s, i) {
  const sn = st.stations[i], stt = status(i), c = COL[stt];
  ctx.fillStyle = '#0f1535'; ctx.fillRect(s.x, s.y, s.w, s.h); glowRect(s.x, s.y, s.w, s.h, sel && sel.k === 's' && sel.i === i ? '#ffffff' : c);
  ctx.fillStyle = '#00ccff'; ctx.font = 'bold 13px Courier New'; ctx.fillText(s.icon + ' ' + s.name, s.x + 8, s.y + 20);
  ctx.fillStyle = c; ctx.font = '11px Courier New'; ctx.fillText('● ' + stt, s.x + 8, s.y + 36);
  ctx.fillStyle = '#ffaa00'; ctx.fillText('queue: ' + sn.queue.length + '  done: ' + sn.processed, s.x + 8, s.y + 52);
  ctx.fillStyle = '#0a0e27'; ctx.fillRect(s.x + 8, s.y + 60, s.w - 16, 8);
  ctx.fillStyle = '#00ff41'; ctx.fillRect(s.x + 8, s.y + 60, (s.w - 16) * (sn.cur ? Math.min(sn.prog, 1) : 0), 8);
}
function pkg(x, y) { ctx.shadowColor = '#00ccff'; ctx.shadowBlur = 10; ctx.fillStyle = '#00ccff'; ctx.fillRect(x - 5, y - 5, 10, 10); ctx.shadowBlur = 0; }
function draw() {
  ctx.fillStyle = '#0a0e27'; ctx.fillRect(0, 0, CFG.w, CFG.h);
  ctx.fillStyle = '#141a40'; ctx.fillRect(20, CFG.corridorY - 30, 920, 60);
  ctx.strokeStyle = 'rgba(0,255,65,.25)'; ctx.setLineDash([8, 8]); ctx.beginPath(); ctx.moveTo(20, CFG.corridorY); ctx.lineTo(940, CFG.corridorY); ctx.stroke(); ctx.setLineDash([]);
  drawCipher(); S.forEach(drawRoom);
  S.forEach((s, i) => { const sn = st.stations[i]; if (sn.cur) pkg(s.x + s.w - 20, s.y + 22 + Math.sin(st.t * 6) * 2); });
  st.agents.forEach(a => {
    const s = S[a.i], bob = a.state === 'idle' ? 0 : Math.sin(st.t * 14) * 3;
    ctx.shadowColor = '#00ff41'; ctx.shadowBlur = 12; ctx.fillStyle = '#1a2d4e'; ctx.strokeStyle = sel && sel.k === 'a' && sel.i === a.i ? '#fff' : '#00ff41'; ctx.lineWidth = 2;
    ctx.beginPath(); ctx.arc(a.x, a.y + bob, 16, 0, 7); ctx.fill(); ctx.stroke(); ctx.shadowBlur = 0;
    ctx.font = '16px serif'; ctx.textAlign = 'center'; ctx.fillStyle = '#fff'; ctx.fillText(s.icon, a.x, a.y + bob + 6);
    ctx.font = '9px Courier New'; ctx.fillStyle = '#00ff41'; ctx.fillText(s.agent, a.x, a.y + bob + 28);
    if (a.pkg) pkg(a.x + 14, a.y + bob - 14);
    ctx.textAlign = 'left';
  });
  st.fx.forEach(f => { ctx.globalAlpha = 1 - f.t / 1.2; ctx.fillStyle = f.c; ctx.font = 'bold 14px Courier New'; ctx.fillText(f.txt, f.x, f.y - f.t * 30); ctx.globalAlpha = 1; });
  ctx.fillStyle = '#12183a'; ctx.fillRect(20, 510, 920, 40); glowRect(20, 510, 920, 40, '#00ccff');
  ctx.fillStyle = '#00ccff'; ctx.font = '12px Courier New';
  ctx.fillText('FLOW: ' + st.spawned + '/' + D.length + ' entered  →  ' + st.done + ' completed  |  ' + st.rejected + ' rejected  |  ' + (finishAll() ? 'ALL DESIGNS PROCESSED' : 'IN PROGRESS'), 32, 535);
  document.getElementById('metrics').textContent = 'Profit $' + st.profit.toFixed(0) + ' | Approved ' + st.done + ' | Rejected ' + st.rejected;
  renderInfo();
}
function renderInfo() {
  const el = document.getElementById('info');
  if (!sel) return;
  if (sel.k === 'a') {
    const a = st.agents[sel.i], s = S[sel.i];
    el.innerHTML = '<b>' + s.icon + ' ' + s.agent + ' AGENT</b> — ' + s.desc + '<br>State: ' + a.state.toUpperCase() + ' | Deliveries: ' + a.delivered + ' | Processed: ' + st.stations[sel.i].processed + ' | Distance walked: ' + Math.round(a.dist) + 'px' + (a.pkg ? ' | Carrying: ' + a.pkg.id : '');
  } else {
    const sn = st.stations[sel.i], s = S[sel.i];
    el.innerHTML = '<b>' + s.icon + ' ' + s.name.toUpperCase() + '</b> — ' + s.desc + '<br>Status: ' + status(sel.i) + ' | Queue: ' + sn.queue.length + ' | Processed: ' + sn.processed + ' | Current: ' + (sn.cur ? sn.cur.id + ' (' + sn.cur.niche + ') ' + Math.round(sn.prog * 100) + '%' : '—');
  }
}
cv.addEventListener('click', e => {
  const r = cv.getBoundingClientRect(), x = (e.clientX - r.left) * CFG.w / r.width, y = (e.clientY - r.top) * CFG.h / r.height;
  sel = null;
  st.agents.forEach(a => { if (Math.hypot(a.x - x, a.y - y) < 20) sel = {k: 'a', i: a.i}; });
  if (!sel) S.forEach((s, i) => { if (x >= s.x && x <= s.x + s.w && y >= s.y && y <= s.y + s.h) sel = {k: 's', i}; });
  if (!sel) document.getElementById('info').textContent = 'Click an agent or a station to inspect it.';
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
