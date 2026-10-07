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

batch = mgr.get("batch", {})
status = batch.get("status", "n/a")
{"GO": st.success, "PARTIAL": st.warning, "NO-GO": st.error}.get(status, st.info)(
    f"Batch launch recommendation: {status}"
)

c1, c2, c3 = st.columns(3)
c1.metric("Greenlit", mgr["approved"])
c2.metric("Revenue (sim)", f"${mgr['total_revenue']:,.2f}")
c3.metric("Profit (sim)", f"${mgr['total_profit']:,.2f}")

scores = pd.DataFrame(
    [{"design_id": k, "score": v["score"], "decision": v["manager_decision"], "coach": v["coach"]}
     for k, v in mgr.get("design_scores", {}).items()]
)
if not scores.empty:
    st.plotly_chart(px.histogram(scores, x="score", color="decision", nbins=15, title="Score distribution"),
                    use_container_width=True)
    st.subheader("Coach feedback for HOLD designs")
    st.dataframe(scores[scores["decision"] == "HOLD"], use_container_width=True)

dec = pd.DataFrame(mgr["decisions"])
counts = dec.groupby(["stage", "action"], as_index=False).size()
st.plotly_chart(px.bar(counts, x="stage", y="size", color="action", title="Manager decisions by stage"),
                use_container_width=True)
st.dataframe(dec, use_container_width=True)
