"""Fallout Shelter-style game arena: agents walk between stations carrying designs."""
import json

STATIONS = [
    ("Trend", "🎯", "Trend Lab", "finds trending niches"),
    ("Research", "🔎", "Market Research", "reviews shop tag signals"),
    ("Design", "💡", "Design Studio", "creates original concepts"),
    ("Prompt", "📝", "Prompt Workshop", "writes prompts"),
    ("Image", "🎨", "Image Studio", "generates images"),
    ("Compliance", "🛡️", "Compliance Office", "checks violations"),
    ("Mockup", "📦", "Mockup Assembly", "selects products"),
    ("Apparel", "🧥", "Sweater & Hoodie", "specializes apparel designs"),
    ("Pricing", "💰", "Pricing Bureau", "sets prices"),
    ("Approval", "✅", "Approval Gate", "approves designs"),
    ("Simulator", "📊", "Market Simulator", "calculates results"),
]


def build_arena_payload(df, max_designs=40):
    """Convert simulation rows into the compact design list that feeds the arena."""
    designs = []
    for _, r in df.head(max_designs).iterrows():
        designs.append({
            "id": str(r["design_id"]),
            "niche": str(r["niche"]),
            "flagged": bool(r["compliance_status"] == "flagged"),
            "approved": bool(r["approved"]),
            "profit": float(r["profit"]) if r["profit"] == r["profit"] else 0.0,
            "revenue": float(r["revenue"]) if r["revenue"] == r["revenue"] else 0.0,
        })
    return {
        "stations": [{"agent": a, "icon": i, "name": n, "desc": d} for a, i, n, d in STATIONS],
        "designs": designs,
    }


def render_arena_html(payload, quote):
    data = json.dumps({"payload": payload, "quote": quote}).replace("</", "<\\/")
    return _TEMPLATE.replace("__DATA__", data)


_TEMPLATE = """
<style>
body{margin:0;background:#0a0e27;color:#00ff41;font-family:monospace}
#bar{display:flex;gap:8px;align-items:center;padding:6px 0;flex-wrap:wrap}
button{background:#0a0e27;color:#00ff41;border:1px solid #00ff41;padding:4px 12px;cursor:pointer;font-family:monospace}
button.on{background:#00ff41;color:#0a0e27}
canvas{width:100%;border:2px solid #00ff41;box-shadow:0 0 12px #00ff41;background:#0a0e27;display:block}
#info{border:1px solid #00ccff;color:#00ccff;padding:8px;margin-top:6px;min-height:44px;font-size:13px}
#metrics{color:#00ccff;margin-left:auto;font-size:13px}
</style>
<div id="bar">
 <button id="play">⏸ PAUSE</button>
 <button data-s="1" class="on">1x</button><button data-s="2">2x</button><button data-s="4">4x</button>
 <button id="reset">↺ RESET</button>
 <span id="metrics"></span>
</div>
<canvas id="c" width="960" height="660"></canvas>
<div id="info">Click an agent or a station to inspect it.</div>
<script>
const D = __DATA__, P = D.payload, W = 960, H = 560;
const cv = document.getElementById('c'), ctx = cv.getContext('2d');
const RW = 210, RH = 150, TOP = 80, GAPX = 20, GAPY = 30, X0 = 10;
let paused = false, speed = 1, sel = null, S;
function roomPos(i) {
  const row = Math.floor(i / 4), position = i % 4;
  const col = row % 2 === 0 ? position : 3 - position;
  return {x: X0 + col * (RW + GAPX), y: TOP + row * (RH + GAPY)};
}
function door(i) { const p = roomPos(i); return {x: p.x + RW / 2, y: p.y + RH - 22}; }
function init() {
  S = {t: 0, spawn: 0, next: 0, done: 0, rejected: 0, approved: 0, profit: 0, revenue: 0, fx: [],
    st: P.stations.map((s, i) => ({q: [], cur: null, prog: 0, processed: 0, ...s})),
    ag: P.stations.map((s, i) => ({i, ...s, ...door(i), tx: 0, ty: 0, mode: 'idle', pkg: null, handled: 0, dist: 0}))};
}
function dur(i) { return 1.2 + (i % 3) * 0.4; }
function finish(a, d) {
  const i = a.i;
  const name = P.stations[i].agent;
  S.st[i].processed++; a.handled++;
  if (name === 'Compliance' && d.flagged) return reject(a, d);
  if (name === 'Approval' && !d.approved) return reject(a, d);
  if (name === 'Approval') S.approved++;
  if (name === 'Simulator') { S.done++; S.profit += d.profit; S.revenue += d.revenue; S.fx.push({x: a.x, y: a.y - 30, t: 0, txt: '+$' + d.profit.toFixed(0)}); return; }
  a.pkg = d; a.mode = 'carry'; const n = door(i + 1); a.tx = n.x; a.ty = n.y;
}
function reject(a, d) { S.rejected++; S.fx.push({x: a.x, y: a.y - 30, t: 0, txt: '✖ ' + d.id, bad: 1}); }
function step(dt) {
  S.t += dt; S.spawn -= dt;
  if (S.spawn <= 0 && S.next < P.designs.length) { S.st[0].q.push(P.designs[S.next++]); S.spawn = 1.0; }
  S.ag.forEach(a => {
    const s = S.st[a.i];
    if (a.mode === 'idle' && !s.cur && s.q.length) { s.cur = s.q.shift(); s.prog = 0; a.mode = 'work'; }
    if (a.mode === 'work') { s.prog += dt / dur(a.i); if (s.prog >= 1) { const d = s.cur; s.cur = null; a.mode = 'idle'; finish(a, d); } }
    if (a.mode === 'carry' || a.mode === 'return') {
      if (a.mode === 'return') { const h = door(a.i); a.tx = h.x; a.ty = h.y; }
      const dx = a.tx - a.x, dy = a.ty - a.y, dist = Math.hypot(dx, dy), v = 160 * dt;
      if (dist <= v) {
        a.x = a.tx; a.y = a.ty;
        if (a.mode === 'carry') { S.st[a.i + 1].q.push(a.pkg); a.pkg = null; a.mode = 'return'; }
        else a.mode = 'idle';
      } else { a.x += dx / dist * v; a.y += dy / dist * v; a.dist += v; }
    }
  });
  S.fx.forEach(f => { f.t += dt; f.y -= 20 * dt; });
  S.fx = S.fx.filter(f => f.t < 1.5);
}
function drawDrCipher(x, y, mood) {
  ctx.fillStyle = '#00ccff';
  ctx.beginPath(); ctx.moveTo(x - 16, y - 8);
  [-18, -10, -2, 6, 14].forEach((dx, k) => { ctx.lineTo(x + dx, y - 30 - (k % 2) * 8); ctx.lineTo(x + dx + 4, y - 12); });
  ctx.lineTo(x + 16, y - 8); ctx.fill();
  ctx.fillStyle = '#ffd7b0'; ctx.beginPath(); ctx.arc(x, y, 14, 0, 7); ctx.fill();
  ctx.fillStyle = '#0a0e27'; ctx.fillRect(x - 7, y - 4, 4, 4); ctx.fillRect(x + 3, y - 4, 4, 4);
  ctx.strokeStyle = '#0a0e27'; ctx.beginPath(); ctx.arc(x, y + 4, 5, mood ? 0.1 : 3.3, mood ? 3 : 6.1); ctx.stroke();
  ctx.fillStyle = '#e8f7ff'; ctx.fillRect(x - 16, y + 14, 32, 14);
}
function draw() {
  ctx.clearRect(0, 0, W, H);
  ctx.fillStyle = '#0d1330'; ctx.fillRect(0, 0, W, H);
  ctx.fillStyle = '#12204a'; ctx.fillRect(0, 0, W, 64);
  drawDrCipher(50, 30, S.rejected <= S.approved);
  ctx.fillStyle = '#00ccff'; ctx.font = 'bold 13px monospace'; ctx.textAlign = 'left';
  ctx.fillText('DR. CIPHER — COMMAND CENTER', 90, 22);
  ctx.fillStyle = '#00ff41'; ctx.font = '12px monospace';
  const q = D.quote.length > 110 ? D.quote.slice(0, 107) + '...' : D.quote;
  ctx.fillText('"' + q + '"', 90, 44);
  S.st.forEach((s, i) => {
    const p = roomPos(i), busy = !!s.cur, hot = sel && sel.k === 's' && sel.i === i;
    ctx.fillStyle = busy ? '#0f2a2a' : '#0b1233'; ctx.fillRect(p.x, p.y, RW, RH);
    ctx.strokeStyle = hot ? '#fff' : busy ? '#00ff41' : '#00ccff'; ctx.lineWidth = hot ? 3 : busy ? 2.5 : 1;
    ctx.shadowColor = ctx.strokeStyle; ctx.shadowBlur = busy ? 14 : 4; ctx.strokeRect(p.x, p.y, RW, RH); ctx.shadowBlur = 0;
    ctx.fillStyle = '#00ff41'; ctx.font = 'bold 13px monospace'; ctx.textAlign = 'left';
    ctx.fillText(s.icon + ' ' + s.name, p.x + 8, p.y + 20);
    ctx.fillStyle = busy ? '#00ff41' : s.q.length ? '#ffaa00' : '#557'; ctx.font = '11px monospace';
    ctx.fillText(busy ? 'BUSY' : s.q.length ? 'WAITING' : 'IDLE', p.x + 8, p.y + 38);
    ctx.fillStyle = '#00ccff'; ctx.fillText('queue ' + s.q.length + ' | done ' + s.processed, p.x + 8, p.y + 54);
    if (busy) { ctx.fillStyle = '#123'; ctx.fillRect(p.x + 8, p.y + 62, RW - 16, 8); ctx.fillStyle = '#00ff41'; ctx.fillRect(p.x + 8, p.y + 62, (RW - 16) * s.prog, 8); }
    for (let k = 0; k < Math.min(s.q.length, 6); k++) { ctx.fillStyle = '#ffaa00'; ctx.fillRect(p.x + 8 + k * 12, p.y + 78, 9, 9); }
    if (i < 7) { const a = door(i), b = door(i + 1); ctx.strokeStyle = 'rgba(0,204,255,.25)'; ctx.setLineDash([4, 6]); ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke(); ctx.setLineDash([]); }
  });
  S.ag.forEach(a => {
    const hot = sel && sel.k === 'a' && sel.i === a.i;
    ctx.fillStyle = a.mode === 'work' ? '#00ff41' : a.mode === 'idle' ? '#00ccff' : '#ffaa00';
    ctx.shadowColor = ctx.fillStyle; ctx.shadowBlur = 10;
    ctx.beginPath(); ctx.arc(a.x, a.y, 12, 0, 7); ctx.fill(); ctx.shadowBlur = 0;
    if (hot) { ctx.strokeStyle = '#fff'; ctx.lineWidth = 2; ctx.stroke(); }
    ctx.fillStyle = '#0a0e27'; ctx.font = '12px monospace'; ctx.textAlign = 'center'; ctx.fillText(a.icon, a.x, a.y + 4);
    ctx.fillStyle = '#00ff41'; ctx.font = '10px monospace'; ctx.fillText(a.agent, a.x, a.y + 24);
    if (a.pkg) { ctx.fillStyle = '#ff00ff'; ctx.fillRect(a.x + 8, a.y - 18, 12, 12); ctx.strokeStyle = '#fff'; ctx.lineWidth = 1; ctx.strokeRect(a.x + 8, a.y - 18, 12, 12); }
  });
  S.fx.forEach(f => { ctx.globalAlpha = Math.max(0, 1 - f.t / 1.5); ctx.fillStyle = f.bad ? '#ff4444' : '#00ff41'; ctx.font = 'bold 13px monospace'; ctx.textAlign = 'center'; ctx.fillText(f.txt, f.x, f.y); ctx.globalAlpha = 1; });
  ctx.textAlign = 'left';
  const total = P.designs.length;
  document.getElementById('metrics').textContent =
    'Spawned ' + S.next + '/' + total + ' | Completed ' + S.done + ' | Approved ' + S.approved + ' | Rejected ' + S.rejected + ' | Profit $' + S.profit.toFixed(0);
  updateInfo();
}
function updateInfo() {
  if (!sel) return;
  const el = document.getElementById('info');
  if (sel.k === 'a') { const a = S.ag[sel.i];
    el.innerHTML = a.icon + ' <b>' + a.agent + ' Agent</b> — ' + a.desc + '<br>Status: ' + a.mode.toUpperCase() + ' | Designs handled: ' + a.handled + ' | Distance walked: ' + Math.round(a.dist) + 'px | Carrying: ' + (a.pkg ? a.pkg.id : 'nothing'); }
  else { const s = S.st[sel.i];
    el.innerHTML = s.icon + ' <b>' + s.name + '</b> — ' + s.desc + '<br>Status: ' + (s.cur ? 'BUSY (' + s.cur.id + ', ' + Math.round(s.prog * 100) + '%)' : s.q.length ? 'WAITING' : 'IDLE') + ' | Queue: ' + s.q.length + ' | Processed: ' + s.processed; }
}
cv.addEventListener('click', e => {
  const r = cv.getBoundingClientRect(), x = (e.clientX - r.left) * W / r.width, y = (e.clientY - r.top) * H / r.height;
  const a = S.ag.find(a => Math.hypot(a.x - x, a.y - y) < 16);
  if (a) { sel = {k: 'a', i: a.i}; return; }
  const i = S.st.findIndex((s, i) => { const p = roomPos(i); return x >= p.x && x <= p.x + RW && y >= p.y && y <= p.y + RH; });
  sel = i >= 0 ? {k: 's', i} : null;
});
const playBtn = document.getElementById('play');
playBtn.onclick = () => { paused = !paused; playBtn.textContent = paused ? '▶ PLAY' : '⏸ PAUSE'; };
document.querySelectorAll('button[data-s]').forEach(b => b.onclick = () => {
  speed = +b.dataset.s; document.querySelectorAll('button[data-s]').forEach(x => x.classList.toggle('on', x === b));
});
document.getElementById('reset').onclick = () => { init(); };
let last = performance.now();
function loop(now) { const dt = Math.min((now - last) / 1000, 0.1); last = now; if (!paused) step(dt * speed); draw(); requestAnimationFrame(loop); }
init(); requestAnimationFrame(loop);
</script>
"""
