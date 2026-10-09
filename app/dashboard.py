import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import json
from pathlib import Path
import pandas as pd
import streamlit as st
import plotly.graph_objects as go
import plotly.express as px
import streamlit.components.v1 as components

import html

from app.arena import build_arena_html, design_payload, recycling_plans
from app.sim import utils as sim_utils
from app.sim.characters import character_from_report

# Same directory the simulator writes to (app.sim.utils.DATA_DIR).
DATA_DIR = sim_utils.DATA_DIR
RECYCLING_PAGE = "pages/5_Recycling.py"

# === PAGE CONFIG & THEME ===
st.set_page_config(
    page_title="AI POD Agent Simulation",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS for game-like theme
st.markdown("""
<style>
    * { font-family: 'Courier New', monospace; }
    
    /* Neon glow effect */
    h1, h2, h3 {
        color: #8cffaa;
        text-shadow: 0 0 8px rgba(0, 255, 65, 0.35);
        font-weight: bold;
    }
    
    /* Dark cyberpunk background */
    .main {
        background: linear-gradient(135deg, #0a0e27 0%, #1a1a3e 100%);
        color: #e7f0ff;
    }
    
    /* Metrics cards */
    [data-testid="metric-container"] {
        background: linear-gradient(135deg, #1a1a3e 0%, #2d1b4e 100%);
        border: 2px solid #00ff41;
        border-radius: 8px;
        padding: 16px;
        box-shadow: 0 0 15px rgba(0, 255, 65, 0.3);
    }
    
    /* Sidebar */
    [data-testid="stSidebar"] {
        background: linear-gradient(135deg, #0a0e27 0%, #1a1a3e 100%);
        border-right: 2px solid #00ff41;
    }
    
    /* Buttons */
    button {
        background: linear-gradient(135deg, #00ff41 0%, #00cc33 100%) !important;
        color: #0a0e27 !important;
        border: none !important;
        border-radius: 6px !important;
        font-weight: bold !important;
        text-shadow: none !important;
    }
    
    button:hover {
        box-shadow: 0 0 15px rgba(0, 255, 65, 0.6) !important;
    }
    
    /* Rick Manager Container */
    .rick-manager {
        background: linear-gradient(135deg, #2d1b4e 0%, #1a2d4e 100%);
        border: 4px solid #ff6b9d;
        border-radius: 16px;
        padding: 30px;
        margin: 20px 0;
        text-align: center;
        box-shadow: 0 0 30px rgba(255, 107, 157, 0.5);
    }
    
    .rick-image-container {
        display: flex;
        justify-content: center;
        align-items: center;
        margin: 15px 0;
        animation: rickBounce 2s infinite;
    }
    
    .rick-image-container img {
        max-height: 280px;
        max-width: 280px;
        filter: drop-shadow(0 0 15px #ff6b9d);
    }
    
    .rick-title {
        color: #ff6b9d;
        font-size: 24px;
        font-weight: bold;
        text-shadow: 0 0 10px #ff6b9d;
    }
    
    .rick-quote {
        color: #00ff41;
        font-size: 14px;
        font-style: italic;
        margin: 10px 0;
        min-height: 40px;
    }
    
    .rick-stats {
        background: linear-gradient(135deg, #1a1a3e 0%, #2d1b4e 100%);
        border: 2px solid #ff6b9d;
        border-radius: 8px;
        padding: 15px;
        margin-top: 15px;
        color: #00ccff;
        font-size: 13px;
    }
    
    /* Achievement badge */
    .achievement {
        background: linear-gradient(135deg, #ff6b00 0%, #ff8c00 100%);
        color: white;
        padding: 12px 16px;
        border-radius: 8px;
        border: 2px solid #ffaa00;
        text-align: center;
        font-weight: bold;
        box-shadow: 0 0 15px rgba(255, 107, 0, 0.5);
        margin: 8px 0;
    }
    
    .stat-box {
        background: linear-gradient(135deg, #1a2d4e 0%, #2d1b4e 100%);
        border: 2px solid #00ccff;
        border-radius: 8px;
        padding: 16px;
        margin: 8px 0;
        box-shadow: 0 0 10px rgba(0, 204, 255, 0.3);
    }
    
    /* Agent Character Card */
    .agent-card {
        background: linear-gradient(135deg, #1a2d4e 0%, #2d1b4e 100%);
        border: 3px solid #00ff41;
        border-radius: 12px;
        padding: 20px;
        margin: 10px;
        text-align: center;
        box-shadow: 0 0 20px rgba(0, 255, 65, 0.4);
        min-width: 140px;
        display: inline-block;
    }
    
    .agent-icon {
        font-size: 48px;
        margin: 10px 0;
        animation: pulse 1.5s infinite;
    }
    
    .agent-name {
        color: #00ccff;
        font-weight: bold;
        font-size: 14px;
        margin: 8px 0;
    }
    
    .agent-role {
        color: #00ff41;
        font-size: 12px;
        margin: 5px 0;
    }
    
    .agent-stats {
        color: #ffaa00;
        font-size: 11px;
        margin-top: 8px;
    }
    
    .progress-bar {
        background: #0a0e27;
        border: 1px solid #00ff41;
        height: 6px;
        border-radius: 3px;
        margin: 8px 0;
        overflow: hidden;
    }
    
    .progress-fill {
        background: linear-gradient(90deg, #00ff41, #00ccff);
        height: 100%;
        border-radius: 3px;
        box-shadow: 0 0 10px rgba(0, 255, 65, 0.6);
    }
    
    @keyframes pulse {
        0%, 100% { transform: scale(1); opacity: 1; }
        50% { transform: scale(1.1); opacity: 0.8; }
    }
    
    @keyframes rickBounce {
        0%, 100% { transform: translateY(0px); }
        50% { transform: translateY(-10px); }
    }
    
    /* Dividers */
    hr {
        border: 1px solid #00ff41;
        box-shadow: 0 0 10px rgba(0, 255, 65, 0.3);
    }
</style>
""", unsafe_allow_html=True)

# === HEADER ===
st.markdown("<h1>🎮 AI POD AGENT SIMULATION ARENA 🎮</h1>", unsafe_allow_html=True)
st.markdown("""
<div style='text-align: center; color: #00ccff; font-size: 14px; margin-bottom: 20px;'>
⚡ MULTI-AGENT PRINT-ON-DEMAND SIMULATION · RECORDED-RUN REPLAY ⚡
</div>
""", unsafe_allow_html=True)


def _list_runs():
    return sorted(DATA_DIR.glob("run_*.json")) if DATA_DIR.exists() else []


def offline_launch(container, key):
    """Explicit, button-triggered offline simulation (no Etsy/OpenAI calls,
    no publishing). Nothing is written unless the button is pressed."""
    with container.form(f"offline_run_{key}"):
        st.markdown("**▶ Run an offline simulation**")
        st.caption("Simulated trends, compliance, pricing and sales; no API calls, no image generation, "
                   "no publishing. Saves a new data/run_*.json (older runs are kept).")
        theme = st.text_input("Theme request (optional)", placeholder="e.g. western, fall, cozy woodland",
                              max_chars=100, key=f"theme_{key}")
        batch = st.number_input("Candidate designs", min_value=4, max_value=60, value=24, step=1,
                                key=f"batch_{key}")
        use_seed = st.checkbox("Fixed seed (reproducible)", value=False, key=f"use_seed_{key}")
        seed = st.number_input("Seed", min_value=0, max_value=1_000_000, value=42, step=1, key=f"seed_{key}")
        submitted = st.form_submit_button("Run offline simulation")
    if not submitted:
        return
    try:
        from app.sim.run_simulation import run_once

        with st.spinner("Running the offline agent pipeline..."):
            path = Path(run_once(batch_size=int(batch), seed=int(seed) if use_seed else None,
                                 theme_request=theme))
    except Exception as exc:  # noqa: BLE001 - show the operator what failed
        st.session_state["launch_error"] = f"Offline simulation failed: {type(exc).__name__}: {exc}"
    else:
        if path.parent.resolve() != DATA_DIR.resolve() or not path.exists():
            st.session_state["launch_error"] = (
                f"Simulation wrote {path} but this dashboard reads {DATA_DIR}; the run cannot be shown.")
        else:
            st.session_state["run_select"] = path.name
            st.session_state["launch_notice"] = f"New run {path.name} saved and selected."
    st.rerun()


if st.session_state.get("launch_error"):
    st.error(st.session_state.pop("launch_error"))
if st.session_state.get("launch_notice"):
    st.success(st.session_state.pop("launch_notice"))

files = _list_runs()
if not files:
    st.warning("⚠️ NO SIMULATION RUNS YET. Start one below (offline, free, nothing is published) or run "
               "`python -m app.sim.run_simulation` in a terminal.")
    offline_launch(st, "main")
    st.stop()

offline_launch(st.sidebar, "sidebar")
names = [f.name for f in files]
if st.session_state.get("run_select") not in names:
    st.session_state["run_select"] = names[-1]
selected = st.sidebar.selectbox("📊 SELECT RUN", names, key="run_select")
with open(DATA_DIR / selected, "r", encoding="utf-8") as f:
    payload = json.load(f)

designs_df = pd.DataFrame(payload.get("designs", []))
results_df = pd.DataFrame(payload.get("results", []))
if designs_df.empty:
    st.info("This simulation run contains no designs.")
    st.stop()
if "design_id" not in designs_df:
    st.error("This simulation run is missing design IDs.")
    st.stop()
if not results_df.empty and "design_id" not in results_df:
    st.error("This simulation run contains results without design IDs.")
    st.stop()
if "design_id" not in results_df:
    results_df["design_id"] = pd.Series(dtype="object")

df = designs_df.merge(results_df, on="design_id", how="left")
for column in (
    "trend_score", "price", "views", "clicks", "ctr", "orders", "revenue", "profit"
):
    if column not in df:
        df[column] = 0
    df[column] = pd.to_numeric(df[column], errors="coerce").fillna(0)
for column, default in (
    ("approved", False),
    ("compliance_status", "pending"),
    ("product_type", "Unknown"),
    ("niche", "Unknown"),
    ("prompt", ""),
    ("compliance_notes", ""),
):
    if column not in df:
        df[column] = default
    else:
        df[column] = df[column].fillna(default)
df["approved"] = df["approved"].astype(bool)

# === CALCULATE STATS ===
total_designs = len(df)
approved = int(df["approved"].sum())
flagged = int((df["compliance_status"] == "flagged").sum())
passed = int((df["compliance_status"] == "pass").sum())
total_revenue = df['revenue'].sum()
total_profit = df['profit'].sum()
approval_rate = (approved / total_designs * 100) if total_designs > 0 else 0

# === DR. CYPHER (OVERSEER) ===
st.markdown("---")

# Dr. Cypher is the Manager agent's character: mood, location and lines come
# from the run's recorded manager decisions (older runs are reconstructed).
cypher = character_from_report(payload.get("manager"))
visit_trail = " → ".join(html.escape(v.get("department", "?")) for v in cypher.visits) or "command"
cipher_html = f"""
<div class="rick-manager">
    <div class="rick-title">🧪 {html.escape(cypher.display_name.upper())} - SIMULATION OVERSEER</div>
    <div class="rick-quote">"{html.escape(cypher.line)}"</div>
    <div class="rick-stats">
        <strong>Lab readout:</strong> {approval_rate:.1f}% Approval Rate | {total_profit:,.0f}$ Total Profit | {total_designs} Designs Processed<br>
        <strong>Mood:</strong> {html.escape(cypher.mood)} | <strong>Rounds this run:</strong> {visit_trail}
    </div>
</div>
"""
st.markdown(cipher_html, unsafe_allow_html=True)

# === GAME ARENA ===
st.markdown("<h2>🏭 THE VAULT: SIMULATION ARENA (REPLAY)</h2>", unsafe_allow_html=True)
st.caption(
    "A timed replay of the selected recorded run (not live backend work): outcomes, worker assignments, "
    "transfers and Dr. Cypher's visits come from the run file; timings are animation. Workers carry each design "
    "between rooms, rejected images with a recycling record go to the Recycling Facility where the recycler's "
    "recorded plan is shown, and Dr. Cypher tours the departments he reviewed (extra patrols are labelled as "
    "replay checks). Click agents, Dr. Cypher, rooms or the worker chips to inspect them."
)


def _recycling_store_records():
    """Read-only view of the global recycling queue (never written here)."""
    from app.sim.recycling import RECYCLING_FILENAME, RecyclingStore

    try:
        return RecyclingStore(DATA_DIR / RECYCLING_FILENAME).records
    except (OSError, ValueError):
        return []


run_plans = recycling_plans(payload.get("recycling"), _recycling_store_records(), selected)
components.html(
    build_arena_html(
        design_payload(df, recycling=payload.get("recycling"), team=payload.get("team"),
                       manager=payload.get("manager")),
        team=payload.get("team"),
        character=cypher.to_dict(),
        run_label=selected,
        plans=run_plans,
    ),
    height=1120,
    scrolling=True,
)
try:
    st.page_link(RECYCLING_PAGE, label="Open the Recycling Facility: preview images, re-analyse, request reuse or archive",
                 icon="♻️")
except Exception:  # noqa: BLE001 - page registry unavailable (e.g. a different entrypoint)
    st.caption("♻️ Open the **Recycling** page in the sidebar to preview images, re-analyse or decide on reuse.")

st.markdown("---")

# === AGENT CHARACTERS ===
st.markdown("<h2>👾 DR. CYPHER'S AGENT TEAM</h2>", unsafe_allow_html=True)
st.markdown("""
<div style='text-align: center; color: #00ff41; font-size: 12px; margin-bottom: 20px;'>
Meet the misfits working under Dr. Cypher's management...
</div>
""", unsafe_allow_html=True)

agents_info = [
    {
        "icon": "🎯",
        "name": "TREND",
        "role": "Trend Scout",
        "stat": f"{total_designs} niches found",
        "progress": 100,
    },
    {
        "icon": "📝",
        "name": "PROMPT",
        "role": "Prompt Writer",
        "stat": f"{total_designs} prompts written",
        "progress": 100,
    },
    {
        "icon": "🎨",
        "name": "IMAGE",
        "role": "Art Generator",
        "stat": f"{total_designs} images created",
        "progress": 100,
    },
    {
        "icon": "🛡️",
        "name": "COMPLIANCE",
        "role": "Rule Enforcer",
        "stat": f"{passed} pass / {flagged} flagged",
        "progress": int((passed / total_designs * 100) if total_designs > 0 else 0),
    },
    {
        "icon": "📦",
        "name": "MOCKUP",
        "role": "Product Designer",
        "stat": f"{total_designs} mockups ready",
        "progress": 100,
    },
    {
        "icon": "💰",
        "name": "PRICING",
        "role": "Price Setter",
        "stat": f"Avg ${df['price'].mean():.2f}",
        "progress": 100,
    },
    {
        "icon": "✅",
        "name": "APPROVAL",
        "role": "Gatekeeper",
        "stat": f"{approved} approved",
        "progress": int((approved / total_designs * 100) if total_designs > 0 else 0),
    },
    {
        "icon": "📊",
        "name": "SIMULATOR",
        "role": "Market Oracle",
        "stat": f"${df['profit'].sum():,.0f} profit",
        "progress": 100,
    },
]
_plans = list(run_plans["plans"].values())
_analysed = sum(1 for p in _plans if p.get("analysis"))
agents_info.append({
    "icon": "♻️",
    "name": "RECYCLER",
    "role": "Reuse Planner",
    "stat": (f"{_analysed}/{len(_plans)} unused images planned" if _plans
             else "no rejected images this run"),
    "progress": int(_analysed / len(_plans) * 100) if _plans else 0,
})

# Display agents in a horizontal pipeline
agents_html = '<div style="display: flex; flex-wrap: wrap; justify-content: center; gap: 5px;">'
for agent in agents_info:
    progress_pct = agent["progress"]
    # Single line per card: indented/blank lines would turn into Markdown code blocks.
    agents_html += (
        f'<div class="agent-card"><div class="agent-icon">{agent["icon"]}</div>'
        f'<div class="agent-name">{html.escape(agent["name"])}</div>'
        f'<div class="agent-role">{html.escape(agent["role"])}</div>'
        f'<div class="progress-bar"><div class="progress-fill" style="width: {progress_pct}%"></div></div>'
        f'<div class="agent-stats">{html.escape(agent["stat"])}</div></div>'
    )
agents_html += '</div>'

st.markdown(agents_html, unsafe_allow_html=True)

# === GAME STATS ===
st.markdown("---")
st.markdown("<h2>🏆 ARENA STATISTICS</h2>", unsafe_allow_html=True)

col1, col2, col3, col4, col5 = st.columns(5)
col1.metric("🎨 DESIGNS", int(len(df)), f"+{len(df)}")
col2.metric("✅ APPROVED", int(df["approved"].sum()), f"+{int(df['approved'].sum())}")
col3.metric("⚠️ FLAGGED", int((df["compliance_status"] == "flagged").sum()), 
            f"-{int((df['compliance_status'] == 'flagged').sum())}")
col4.metric("💰 REVENUE", f"${df['revenue'].sum():,.0f}", f"+${df['revenue'].sum():,.0f}")
col5.metric("🎯 PROFIT", f"${df['profit'].sum():,.0f}", f"+${df['profit'].sum():,.0f}")

st.markdown("---")

# === LEVEL PROGRESS ===
total_designs = len(df)
approved_designs = int(df["approved"].sum())
progress = (approved_designs / total_designs * 100) if total_designs > 0 else 0

st.markdown("<h3>⚔️ AGENT COMPLETION LEVEL</h3>", unsafe_allow_html=True)
st.progress(min(progress / 100, 1.0))
st.markdown(f"<div style='text-align: center; color: #00ccff;'>{progress:.1f}% MISSION COMPLETE</div>", unsafe_allow_html=True)

# === ACHIEVEMENTS ===
st.markdown("---")
st.markdown("<h3>🏅 ACHIEVEMENTS UNLOCKED</h3>", unsafe_allow_html=True)

achievements = []
if approved_designs >= 1:
    achievements.append("🚀 FIRST LAUNCH - Approved first design")
if approved_designs >= 5:
    achievements.append("⚡ SPEEDRUNNER - 5+ designs approved")
if approved_designs >= 10:
    achievements.append("🔥 HOT STREAK - 10+ designs approved")
if df['revenue'].sum() >= 100:
    achievements.append("💎 FORTUNE MAKER - $100+ revenue")
if df['profit'].sum() >= 50:
    achievements.append("🎯 PROFIT MASTER - $50+ profit")
if int((df["compliance_status"] == "pass").sum()) >= 3:
    achievements.append("🛡️ CLEAN SWEEP - 3+ compliance passes")
if df['ctr'].max() >= 0.1:
    achievements.append("👁️ VIRAL DESIGN - 10%+ CTR achieved")

if achievements:
    for achievement in achievements:
        st.markdown(f"<div class='achievement'>{achievement}</div>", unsafe_allow_html=True)
else:
    st.info("🎮 Keep playing to unlock achievements!")

# === PIPELINE BATTLE ===
st.markdown("---")
st.markdown("<h3>⚙️ PIPELINE STAGE BREAKDOWN</h3>", unsafe_allow_html=True)

pipeline_counts = pd.DataFrame({
    "Stage": ["✅ PASS", "⚠️ FLAGGED", "🎯 APPROVED", "❌ REJECTED"],
    "Count": [
        int((df["compliance_status"] == "pass").sum()),
        int((df["compliance_status"] == "flagged").sum()),
        int(df["approved"].sum()),
        int((~df["approved"]).sum()),
    ],
})

fig_pipe = px.bar(
    pipeline_counts, 
    x="Stage", 
    y="Count",
    color="Stage",
    color_discrete_map={
        "✅ PASS": "#00ff41",
        "⚠️ FLAGGED": "#ffaa00",
        "🎯 APPROVED": "#00ccff",
        "❌ REJECTED": "#ff4444",
    },
    title="AGENT WORKFLOW OUTCOMES",
    labels={"Count": "Quantity"}
)
fig_pipe.update_layout(
    plot_bgcolor="#0a0e27",
    paper_bgcolor="#0a0e27",
    font=dict(color="#00ff41", size=12),
    title_font=dict(color="#00ff41", size=16),
    hovermode="x unified",
    showlegend=False,
)
st.plotly_chart(fig_pipe, use_container_width=True)

# === MARKET LEADERBOARD ===
left, right = st.columns(2)

with left:
    st.markdown("<h3>🎁 PROFIT BY PRODUCT CLASS</h3>", unsafe_allow_html=True)
    profit_by_product = df.groupby("product_type", as_index=False)["profit"].sum().sort_values("profit", ascending=False)
    
    fig_profit = px.bar(
        profit_by_product,
        x="product_type",
        y="profit",
        color="profit",
        color_continuous_scale=["#ff4444", "#ffaa00", "#00ff41"],
        title="TOP REVENUE GENERATORS",
        labels={"product_type": "Product", "profit": "Profit ($)"}
    )
    fig_profit.update_layout(
        plot_bgcolor="#0a0e27",
        paper_bgcolor="#0a0e27",
        font=dict(color="#00ff41", size=12),
        title_font=dict(color="#00ff41", size=14),
        showlegend=False,
    )
    st.plotly_chart(fig_profit, use_container_width=True)

with right:
    st.markdown("<h3>🌟 NICHE PERFORMANCE RANKING</h3>", unsafe_allow_html=True)
    niche_stats = df.groupby("niche", as_index=False)[["orders", "revenue", "profit"]].sum()
    niche_stats["rank"] = niche_stats["profit"].rank(ascending=False, method="min").astype(int)
    niche_stats = niche_stats.sort_values("rank")
    
    fig_niche = px.scatter(
        niche_stats,
        x="orders",
        y="profit",
        size="revenue",
        color="rank",
        hover_name="niche",
        color_continuous_scale="Viridis",
        title="NICHE POSITIONING MAP",
        labels={"orders": "Orders", "profit": "Profit ($)"}
    )
    fig_niche.update_layout(
        plot_bgcolor="#0a0e27",
        paper_bgcolor="#0a0e27",
        font=dict(color="#00ff41", size=12),
        title_font=dict(color="#00ff41", size=14),
    )
    st.plotly_chart(fig_niche, use_container_width=True)

# === NICHE LEADERBOARD ===
st.markdown("---")
st.markdown("<h3>🏅 NICHE LEADERBOARD</h3>", unsafe_allow_html=True)

metrics_by_niche = df.groupby("niche", as_index=False)[["views", "clicks", "orders", "revenue", "profit"]].sum()
metrics_by_niche["ctr"] = (
    metrics_by_niche["clicks"]
    .div(metrics_by_niche["views"].where(metrics_by_niche["views"] != 0))
    .fillna(0)
    .mul(100)
    .round(2)
)
metrics_by_niche["rank"] = metrics_by_niche["profit"].rank(ascending=False, method="min").astype(int)
metrics_by_niche = metrics_by_niche.sort_values("rank")

display_cols = ["rank", "niche", "orders", "views", "ctr", "revenue", "profit"]
leaderboard_df = metrics_by_niche[display_cols].copy()
leaderboard_df.columns = ["🥇 Rank", "📍 Niche", "📦 Orders", "👁️ Views", "📊 CTR %", "💵 Revenue", "🎯 Profit"]

st.dataframe(
    leaderboard_df,
    use_container_width=True,
    hide_index=True,
)

# === TOP DESIGNS ===
st.markdown("---")
st.markdown("<h3>🌟 TOP 10 PERFORMING DESIGNS</h3>", unsafe_allow_html=True)

top_designs = df.nlargest(10, "profit")[
    ["design_id", "niche", "trend_score", "product_type", "price", "orders", "revenue", "profit"]
].copy()
top_designs.columns = ["🎨 Design ID", "📍 Niche", "📈 Trend", "🎁 Product", "💲 Price", "📦 Orders", "💵 Revenue", "🎯 Profit"]

st.dataframe(top_designs, use_container_width=True, hide_index=True)

# === DETAILED DESIGN GALLERY ===
st.markdown("---")
st.markdown("<h3>🎮 FULL DESIGN REGISTRY</h3>", unsafe_allow_html=True)

filters = st.columns([2, 1, 1])
search = filters[0].text_input("Search designs", placeholder="ID, niche, product, or compliance note")
niches = ["All niches", *sorted(df["niche"].astype(str).unique())]
selected_niche = filters[1].selectbox("Niche", niches)
statuses = ["All statuses", *sorted(df["compliance_status"].astype(str).unique())]
selected_status = filters[2].selectbox("Compliance", statuses)

filtered_df = df.copy()
if search:
    search_columns = ["design_id", "niche", "product_type", "compliance_status", "compliance_notes"]
    matches = filtered_df[search_columns].astype(str).apply(
        lambda column: column.str.contains(search, case=False, regex=False)
    ).any(axis=1)
    filtered_df = filtered_df[matches]
if selected_niche != "All niches":
    filtered_df = filtered_df[filtered_df["niche"].astype(str) == selected_niche]
if selected_status != "All statuses":
    filtered_df = filtered_df[filtered_df["compliance_status"].astype(str) == selected_status]

show_cols = [
    "design_id",
    "niche",
    "trend_score",
    "compliance_status",
    "product_type",
    "price",
    "approved",
    "views",
    "clicks",
    "ctr",
    "orders",
    "revenue",
    "profit",
]
display_df = filtered_df[show_cols].copy()
display_df.columns = ["🎨 ID", "📍 Niche", "📈 Score", "🛡️ Status", "🎁 Product", "💲 $", "✅", "👁️", "🖱️", "CTR", "📦", "💵", "🎯"]

st.dataframe(display_df, use_container_width=True, hide_index=True)

if filtered_df.empty:
    st.info("No designs match these filters.")
else:
    selected_design_id = st.selectbox(
        "Inspect design",
        filtered_df["design_id"].astype(str).tolist(),
        key=f"inspect_{selected}",
    )
    design = filtered_df[filtered_df["design_id"].astype(str) == selected_design_id].iloc[0]
    manager = payload.get("manager", {})
    manager_score = manager.get("design_scores", {}).get(selected_design_id, {})

    st.markdown("#### Design detail")
    detail_cols = st.columns(4)
    detail_cols[0].metric("Manager score", f"{manager_score.get('score', '—')}")
    detail_cols[1].metric("Decision", manager_score.get("manager_decision", "Not scored"))
    detail_cols[2].metric("Compliance", str(design["compliance_status"]).title())
    detail_cols[3].metric("Profit", f"${design['profit']:,.2f}")

    with st.container(border=True):
        prompt_col, review_col = st.columns(2)
        with prompt_col:
            st.markdown("**Design brief**")
            st.write(design["prompt"] or "No prompt recorded for this design.")
            st.caption(f"{design['product_type']} · {design['niche']} · Trend score {design['trend_score']:.2f}")
        with review_col:
            st.markdown("**Agent review**")
            st.write(design["compliance_notes"] or "No compliance notes recorded.")
            if manager_score.get("coach"):
                st.info(manager_score["coach"])
            score_components = manager_score.get("components", {})
            if score_components:
                st.markdown("**Score breakdown**")
                st.dataframe(
                    pd.DataFrame(
                        [{"Factor": name.title(), "Score": score} for name, score in score_components.items()]
                    ),
                    use_container_width=True,
                    hide_index=True,
                )

# === GAME TIPS ===
st.markdown("---")
st.markdown("""
<div style='background: linear-gradient(135deg, #1a2d4e 0%, #2d1b4e 100%); 
            border: 2px solid #00ccff; border-radius: 8px; padding: 16px; 
            box-shadow: 0 0 10px rgba(0, 204, 255, 0.3);'>
<h4 style='color: #00ccff;'>💡 AGENT SURVIVAL TIPS (From Dr. Cypher)</h4>
<ul style='color: #00ff41;'>
    <li>⚡ Higher trend scores = better marketplace performance</li>
    <li>🛡️ Compliance checks prevent costly rejections</li>
    <li>💰 Volume × Margin = Profit. Balance both! (it's science)</li>
    <li>🎯 CTR > 5% unlocks premium status</li>
    <li>🔄 Run simulations multiple times to optimize (I didn't invent optimization for nothing)</li>
</ul>
</div>
""", unsafe_allow_html=True)

st.markdown("---")
st.caption("🤖 AI POD Agent Simulation v3.0 | Dr. Cypher's Multi-Agent Print-On-Demand Arena")
