import json
from pathlib import Path
import pandas as pd
import streamlit as st
import plotly.graph_objects as go
import plotly.express as px
import streamlit.components.v1 as components

from app.arena import build_arena_payload, render_arena_html

DATA_DIR = Path(__file__).resolve().parents[1] / "data"

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
        color: #00ff41;
        text-shadow: 0 0 10px #00ff41, 0 0 20px #00ff41;
        font-weight: bold;
    }
    
    /* Dark cyberpunk background */
    .main {
        background: linear-gradient(135deg, #0a0e27 0%, #1a1a3e 100%);
        color: #00ff41;
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
⚡ REAL-TIME MULTI-AGENT PRINT-ON-DEMAND MARKETPLACE BATTLE ⚡
</div>
""", unsafe_allow_html=True)

if not DATA_DIR.exists():
    st.error("❌ NO DATA DIRECTORY FOUND. INITIALIZING SIMULATION...")
    st.stop()

files = sorted(DATA_DIR.glob("run_*.json"))
if not files:
    st.warning("⚠️ NO SIMULATION RUNS DETECTED. LAUNCH SIMULATION: python -m app.sim.run_simulation")
    st.stop()

selected = st.sidebar.selectbox("📊 SELECT RUN", [f.name for f in files], index=len(files)-1)
with open(DATA_DIR / selected, "r", encoding="utf-8") as f:
    payload = json.load(f)

designs_df = pd.DataFrame(payload["designs"])
results_df = pd.DataFrame(payload["results"])
df = designs_df.merge(results_df, on="design_id", how="left")

# === CALCULATE STATS ===
total_designs = len(df)
approved = int(df["approved"].sum())
flagged = int((df["compliance_status"] == "flagged").sum())
passed = int((df["compliance_status"] == "pass").sum())
total_revenue = df['revenue'].sum()
total_profit = df['profit'].sum()
approval_rate = (approved / total_designs * 100) if total_designs > 0 else 0

# === RICK MANAGER (OVERSEER) ===
st.markdown("---")

# Generate Rick's quote based on performance
rick_quotes = {
    "excellent": [
        "Wubba lubba dub dub! Now THAT'S a simulation! 🤢 *burp* Impressive.",
        "Burp! Not bad, not bad at all. Your agents actually know what they're doing.",
        "*burp* I've seen worse. Much worse. Like Morty-level worse.",
    ],
    "good": [
        "Eh, I guess that's acceptable. *burp* Could be better though.",
        "Look, it's functional. That's all I'm saying. *burp*",
        "Not terrible. I mean, I've done better in my sleep. *burp*",
    ],
    "mediocre": [
        "Aw geez, really? That's the best you could do? *burp*",
        "*burp* I don't want to say I'm disappointed, but... actually, I do.",
        "This is what happens when you rely on AGENTS, Morty— I mean, when you run simulations poorly.",
    ],
    "poor": [
        "What is THIS?! *burp* Did Morty write this code? Ugh.",
        "*burp* I've seen better performance from a PICKLE, and I was one.",
        "Aw man, this is BAD. Like, really bad. We need to get schwifty with optimization.",
    ]
}

if approval_rate >= 70:
    rick_quote = rick_quotes["excellent"][hash(str(approved)) % len(rick_quotes["excellent"])]
elif approval_rate >= 50:
    rick_quote = rick_quotes["good"][hash(str(approved)) % len(rick_quotes["good"])]
elif approval_rate >= 30:
    rick_quote = rick_quotes["mediocre"][hash(str(approved)) % len(rick_quotes["mediocre"])]
else:
    rick_quote = rick_quotes["poor"][hash(str(approved)) % len(rick_quotes["poor"])]

rick_html = f"""
<div class="rick-manager">
    <div class="rick-image-container">
        <img src="https://raw.githubusercontent.com/RussellParker123/ai-pod-agent-sim/main/assets/rick.png" alt="Rick Sanchez" onerror="this.style.display='none'">
    </div>
    <div class="rick-title">RICK SANCHEZ - SIMULATION OVERLORD</div>
    <div class="rick-quote">"{rick_quote}"</div>
    <div class="rick-stats">
        <strong>Portal Gun Reading:</strong> {approval_rate:.1f}% Approval Rate | {total_profit:,.0f}$ Total Profit | {total_designs} Designs Processed
    </div>
</div>
"""
st.markdown(rick_html, unsafe_allow_html=True)

# === GAME ARENA ===
st.markdown("<h2>🕹️ SIMULATION ARENA</h2>", unsafe_allow_html=True)
components.html(render_arena_html(build_arena_payload(df), rick_quote), height=700)

st.markdown("---")

# === AGENT CHARACTERS ===
st.markdown("<h2>👾 RICK'S AGENT TEAM</h2>", unsafe_allow_html=True)
st.markdown("""
<div style='text-align: center; color: #00ff41; font-size: 12px; margin-bottom: 20px;'>
Meet the misfits working under Rick's tyrannical management...
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

# Display agents in a horizontal pipeline
agents_html = '<div style="display: flex; flex-wrap: wrap; justify-content: center; gap: 5px;">'
for agent in agents_info:
    progress_pct = agent["progress"]
    agents_html += f"""
    <div class="agent-card">
        <div class="agent-icon">{agent['icon']}</div>
        <div class="agent-name">{agent['name']}</div>
        <div class="agent-role">{agent['role']}</div>
        <div class="progress-bar">
            <div class="progress-fill" style="width: {progress_pct}%"></div>
        </div>
        <div class="agent-stats">{agent['stat']}</div>
    </div>
    """
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
metrics_by_niche["ctr"] = (metrics_by_niche["clicks"] / metrics_by_niche["views"] * 100).round(2)
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
display_df = df[show_cols].copy()
display_df.columns = ["🎨 ID", "📍 Niche", "📈 Score", "🛡️ Status", "🎁 Product", "💲 $", "✅", "👁️", "🖱️", "CTR", "📦", "💵", "🎯"]

st.dataframe(display_df, use_container_width=True, hide_index=True)

# === GAME TIPS ===
st.markdown("---")
st.markdown("""
<div style='background: linear-gradient(135deg, #1a2d4e 0%, #2d1b4e 100%); 
            border: 2px solid #00ccff; border-radius: 8px; padding: 16px; 
            box-shadow: 0 0 10px rgba(0, 204, 255, 0.3);'>
<h4 style='color: #00ccff;'>💡 AGENT SURVIVAL TIPS (From Rick)</h4>
<ul style='color: #00ff41;'>
    <li>⚡ Higher trend scores = better marketplace performance (obvious, even for Morty)</li>
    <li>🛡️ Compliance checks prevent costly rejections (don't be an idiot)</li>
    <li>💰 Volume × Margin = Profit. Balance both! (it's science, burp)</li>
    <li>🎯 CTR > 5% unlocks premium status (get schwifty with marketing)</li>
    <li>🔄 Run simulations multiple times to optimize (I didn't invent optimization for nothing)</li>
</ul>
</div>
""", unsafe_allow_html=True)

st.markdown("---")
st.caption("🤖 AI POD Agent Simulation v3.0 | Rick's Multi-Agent Print-On-Demand Arena | Burp")
