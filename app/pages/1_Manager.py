import json
from pathlib import Path
import pandas as pd
import streamlit as st
import plotly.express as px

DATA_DIR = Path(__file__).resolve().parents[2] / "data"

st.title("Manager Agent Oversight")

files = sorted(DATA_DIR.glob("run_*.json")) if DATA_DIR.exists() else []
if not files:
    st.warning("No runs yet. Run: python -m app.sim.run_simulation")
    st.stop()

selected = st.selectbox("Select run", [f.name for f in files], index=len(files) - 1)
payload = json.loads((DATA_DIR / selected).read_text(encoding="utf-8"))
mgr = payload.get("manager")
if not mgr:
    st.info("This run has no manager data. Generate a new run.")
    st.stop()

c1, c2, c3 = st.columns(3)
c1.metric("Approved", mgr["approved"])
c2.metric("Revenue", f"${mgr['total_revenue']:,.2f}")
c3.metric("Profit", f"${mgr['total_profit']:,.2f}")

dec = pd.DataFrame(mgr["decisions"])
counts = dec.groupby(["stage", "action"], as_index=False).size()
st.plotly_chart(px.bar(counts, x="stage", y="size", color="action", title="Manager decisions by stage"),
                use_container_width=True)

stage = st.multiselect("Filter stage", sorted(dec["stage"].unique()), default=list(dec["stage"].unique()))
st.dataframe(dec[dec["stage"].isin(stage)], use_container_width=True)
