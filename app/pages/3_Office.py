"""Office view: department desks with the agents actually assigned to them,
Dr. Cypher walking to the departments he reviewed, and a transfer control."""
import html
import json
import sys
import time
from pathlib import Path

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.sim.characters import character_from_report  # noqa: E402
from app.sim.team import TransferError, agents_for, load_team_state, save_team_state, transfer_events  # noqa: E402
from app.utils.dr_cipher import get_dr_cipher_svg  # noqa: E402

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
TEAM_STATE_PATH = DATA_DIR / "team_state.json"

DEPARTMENTS = [
    ("trend", "🔎", "Trend Lab", "Market research"),
    ("prompt", "✍️", "Prompt Workshop", "Product-aware briefs"),
    ("image", "🎨", "Image Studio", "Art generation"),
    ("compliance", "🛡️", "Compliance Office", "Trademark & similarity"),
    ("mockup", "👕", "Mockup Assembly", "Mugs, shirts, totes"),
    ("pricing", "💲", "Pricing Bureau", "Margins"),
    ("marketing", "📣", "Marketing Desk", "Titles & tags"),
    ("recycling", "♻️", "Recycling Facility", "Reuse of rejected art"),
]

CSS = """
<style>
 body{margin:0;font-family:Segoe UI,Arial,sans-serif;background:#1e2430;}
 .office{background:#e9e2d0;border:6px solid #3b4252;border-radius:14px;padding:14px;}
 .mgr-room{background:rgba(120,180,220,.25);border:3px solid #6fa8c9;border-radius:12px;padding:8px;
   display:flex;justify-content:center;margin-bottom:14px;}
 .floor{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;}
 .desk{position:relative;background:#c9a66b;border-radius:10px;padding:10px;text-align:center;
   box-shadow:0 4px 0 #8b6b3d;min-height:130px;transition:all .3s;}
 .desk.recycling{background:#9fd3a8;box-shadow:0 4px 0 #4f8a5a;}
 .desk.active{background:#ffe08a;box-shadow:0 0 18px 4px #ffb300;transform:translateY(-3px);}
 .avatar{font-size:30px;line-height:1.1;}
 .name{font-weight:700;font-size:13px;color:#2b2b2b;}
 .role{font-size:11px;color:#444;}
 .staff{margin-top:6px;display:flex;flex-wrap:wrap;gap:4px;justify-content:center;}
 .agent{background:#2b3245;color:#7CFC9A;border-radius:6px;padding:2px 6px;font:11px monospace;}
 .agent.away{color:#ff9ec4;border:1px dashed #ff9ec4;}
 .cypher{position:absolute;top:-16px;right:-8px;font-size:30px;animation:bob .8s infinite ease-in-out;}
 .bubble{position:absolute;top:-46px;left:50%;transform:translateX(-50%);background:#fff;color:#222;
   border:2px solid #333;border-radius:10px;padding:4px 8px;font-size:11px;width:210px;z-index:5;}
 .mgr-room .desk{width:320px;}
 @keyframes bob{0%,100%{transform:translateY(0)}50%{transform:translateY(-6px)}}
</style>
"""


def roster_by_department(agents):
    out = {}
    for agent_id, agent in sorted(agents.items()):
        out.setdefault(agent.get("current_department"), []).append(agent)
    return out


def desk_html(key, emoji, name, role, staff, cypher_here, bubble):
    cls = "desk" + (" recycling" if key == "recycling" else "") + (" active" if cypher_here else "")
    chips = "".join(
        f'<span class="agent{" away" if a.get("home_department") != key else ""}" '
        f'title="home: {html.escape(str(a.get("home_department")))}">{html.escape(str(a.get("agent_id")))}</span>'
        for a in staff
    ) or '<span class="role">no team workers</span>'
    visitor = '<div class="cypher" title="Dr. Cypher">🧪</div>' if cypher_here else ""
    talk = f'<div class="bubble">{html.escape(bubble)}</div>' if cypher_here and bubble else ""
    return (f'<div class="{cls}">{talk}{visitor}<div class="avatar">{emoji}</div>'
            f'<div class="name">{html.escape(name)}</div><div class="role">{html.escape(role)}</div>'
            f'<div class="staff">{chips}</div></div>')


def office_html(agents, cypher_location, line):
    by_dept = roster_by_department(agents)
    at_command = cypher_location not in {d[0] for d in DEPARTMENTS}
    mgr = desk_html("command", "🧑‍🔬", "Dr. Cypher's Command Center", "Oversight & greenlight", [], at_command,
                    line if at_command else "")
    desks = "".join(
        desk_html(key, emoji, name, role, by_dept.get(key, []), cypher_location == key, line)
        for key, emoji, name, role in DEPARTMENTS
    )
    return f'{CSS}<div class="office"><div class="mgr-room">{mgr}</div><div class="floor">{desks}</div></div>'


files = sorted(DATA_DIR.glob("run_*.json")) if DATA_DIR.exists() else []
st.title("The Office")
if not files:
    st.warning("No runs yet. Run: python -m app.sim.run_simulation")
    st.stop()

run = st.selectbox("Select run", [f.name for f in files], index=len(files) - 1)
payload = json.loads((DATA_DIR / run).read_text(encoding="utf-8"))
team_report = payload.get("team")
agents = agents_for(team_report)
cypher = character_from_report(payload.get("manager"))

# --- Dr. Cypher ---------------------------------------------------------------
left, right = st.columns([1, 2])
with left:
    st.markdown(get_dr_cipher_svg(), unsafe_allow_html=True)
with right:
    st.subheader(f"🧪 {cypher.display_name}")
    st.caption(f"{cypher.title} · id `{cypher.character_id}` · manager `{cypher.manager_id}`")
    st.markdown(
        f"**Mood:** {html.escape(cypher.mood)} &nbsp;|&nbsp; **Location:** {html.escape(cypher.location)} "
        f"&nbsp;|&nbsp; **Activity:** {html.escape(cypher.activity)}",
        unsafe_allow_html=True,
    )
    st.markdown(f"> {html.escape(cypher.line)}", unsafe_allow_html=True)
    st.caption(cypher.personality)
    if cypher.visits:
        st.dataframe(
            pd.DataFrame([{"#": v.get("seq"), "department": v.get("department"), "purpose": v.get("purpose"),
                           "said": v.get("line"), "designs": len(v.get("design_ids", []))} for v in cypher.visits]),
            hide_index=True, use_container_width=True,
        )

# --- Office playback (replay of this run's recorded visits) -------------------
st.markdown("### Office floor (replay of recorded run)")
st.caption("Desks show the agents assigned to each department at the end of this run (dashed = away from home). "
           "Dr. Cypher's walk replays the department visits recorded by the Manager; it is not live backend work.")
visits = cypher.visits
step = st.slider("Dr. Cypher visit (0 = command center)", 0, len(visits), 0) if visits else 0
play = st.button("▶ Replay Dr. Cypher's rounds", disabled=not visits)
slot = st.empty()


def frame(i):
    if i == 0:
        return office_html(agents, "command", cypher.line)
    visit = visits[i - 1]
    return office_html(agents, visit.get("department"), visit.get("line", ""))


if play:
    for i in range(1, len(visits) + 1):
        with slot:
            components.html(frame(i), height=560)
        time.sleep(1.4)
else:
    with slot:
        components.html(frame(step), height=560)

events = transfer_events(team_report)
st.markdown("### Movements recorded in this run")
if events:
    st.dataframe(pd.DataFrame(events), hide_index=True, use_container_width=True)
else:
    st.caption("No department transfers happened during this run.")

# --- Roster for the next run ---------------------------------------------------
st.markdown("### Transfer agents for the next run")
st.caption(
    "The simulator loads this roster (data/team_state.json) at the start of each run, so a transfer changes "
    "which agents the next run assigns work to. Agents can only move within their skill group "
    "(creative: prompt/image · review: compliance/recycling · commerce: mockup/pricing/marketing), "
    "and every department keeps at least one worker."
)
team = load_team_state(TEAM_STATE_PATH)
roster = pd.DataFrame([
    {"agent": a["agent_id"], "home": a["home_department"], "current": a["current_department"],
     "can work in": ", ".join(a["capabilities"]), "moves": len(a["history"])}
    for a in team.agents.values()
])
st.dataframe(roster, hide_index=True, use_container_width=True)

with st.form("transfer"):
    agent_id = st.selectbox("Agent", sorted(team.agents))
    destination = st.selectbox("Destination department", sorted(team.workers))
    reason = st.text_input("Reason", value="manual rebalancing")
    submitted = st.form_submit_button("Transfer agent")
if submitted:
    try:
        event = team.transfer(agent_id, destination, reason=reason[:200], initiated_by="user")
        save_team_state(team, TEAM_STATE_PATH)
        st.success(f"{event['agent_id']} moved {event['from']} → {event['to']}. Takes effect in the next run.")
        st.rerun()
    except TransferError as exc:
        st.error(str(exc))

if st.button("Return everyone to their home department"):
    moved, errors = 0, []
    for aid, agent in team.agents.items():
        if agent["current_department"] != agent["home_department"]:
            try:
                team.transfer(aid, agent["home_department"], reason="return home", initiated_by="user")
                moved += 1
            except TransferError as exc:
                errors.append(str(exc))
    save_team_state(team, TEAM_STATE_PATH)
    st.info(f"Returned {moved} agent(s) home." + (" Issues: " + "; ".join(errors) if errors else ""))

st.caption("Use the Review page to cancel or override anything the Manager greenlit; the Recycling page "
           "handles rejected art.")
