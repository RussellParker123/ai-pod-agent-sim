import json
from pathlib import Path
import pandas as pd
import streamlit as st
import plotly.express as px

DATA_DIR = Path(__file__).resolve().parents[1] / "data"

st.set_page_config(page_title="AI POD Agent Simulation", layout="wide")
st.title("AI POD Agent Simulation Dashboard")

if not DATA_DIR.exists():
    st.error("No data directory found. Run: python -m app.sim.run_simulation")
    st.stop()

files = sorted(DATA_DIR.glob("run_*.json"))
if not files:
    st.warning("No simulation runs found yet. Run: python -m app.sim.run_simulation")
    st.stop()

selected = st.selectbox("Select run", [f.name for f in files], index=len(files)-1)
with open(DATA_DIR / selected, "r", encoding="utf-8") as f:
    payload = json.load(f)

designs_df = pd.DataFrame(payload["designs"])
results_df = pd.DataFrame(payload["results"])
df = designs_df.merge(results_df, on="design_id", how="left")

# Top metrics
col1, col2, col3, col4, col5 = st.columns(5)
col1.metric("Designs", int(len(df)))
col2.metric("Approved", int(df["approved"].sum()))
col3.metric("Flagged", int((df["compliance_status"] == "flagged").sum()))
col4.metric("Revenue", f"${df['revenue'].sum():,.2f}")
col5.metric("Profit", f"${df['profit'].sum():,.2f}")

st.markdown("---")

left, right = st.columns(2)

with left:
    st.subheader("Pipeline / Compliance")
    pipeline_counts = pd.DataFrame(
        {
            "stage": ["pass", "flagged", "approved", "rejected"],
            "count": [
                int((df["compliance_status"] == "pass").sum()),
                int((df["compliance_status"] == "flagged").sum()),
                int(df["approved"].sum()),
                int((~df["approved"]).sum()),
            ],
        }
    )
    fig_pipe = px.bar(pipeline_counts, x="stage", y="count", title="Agent Outcomes")
    st.plotly_chart(fig_pipe, use_container_width=True)

with right:
    st.subheader("Profit by Product Type")
    fig_profit = px.bar(
        df.groupby("product_type", as_index=False)["profit"].sum(),
        x="product_type",
        y="profit",
        title="Profit by Product",
    )
    st.plotly_chart(fig_profit, use_container_width=True)

st.subheader("Marketplace Metrics")
metrics_by_niche = (
    df.groupby("niche", as_index=False)[["views", "clicks", "orders", "revenue", "profit"]].sum()
)
st.dataframe(metrics_by_niche, use_container_width=True)

st.subheader("Design Gallery / Listing Table")
show_cols = [
    "design_id",
    "niche",
    "trend_score",
    "prompt",
    "image_uri",
    "compliance_status",
    "compliance_notes",
    "product_type",
    "unit_cost",
    "price",
    "approved",
    "views",
    "clicks",
    "ctr",
    "conversion_rate",
    "orders",
    "revenue",
    "profit",
]
st.dataframe(df[show_cols], use_container_width=True)
