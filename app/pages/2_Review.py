"""Review page: see what the Manager passed and manually cancel / override.

Overrides are saved to data/overrides.json and never alter the original run file.
- cancel:         stop a design the manager passed (GREENLIGHT or HOLD)
- force_approve:  push a HOLD design through. Compliance-blocked designs can NOT be forced.
"""
import json
from pathlib import Path
import pandas as pd
import streamlit as st

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
OVERRIDES = DATA_DIR / "overrides.json"

st.title("Review & Override")

files = sorted(DATA_DIR.glob("run_*.json")) if DATA_DIR.exists() else []
if not files:
    st.warning("No runs yet. Run: python -m app.sim.run_simulation")
    st.stop()

run = st.selectbox("Select run", [f.name for f in files], index=len(files) - 1)
payload = json.loads((DATA_DIR / run).read_text(encoding="utf-8"))
mgr = payload.get("manager", {})
scores = mgr.get("design_scores")
if not scores:
    st.info("This run has no manager scoring. Generate a new run.")
    st.stop()

all_over = json.loads(OVERRIDES.read_text()) if OVERRIDES.exists() else {}
run_over = all_over.get(run, {})

designs = {d["design_id"]: d for d in payload["designs"]}
rows = []
for did, s in scores.items():
    d = designs.get(did, {})
    rows.append({
        "design_id": did,
        "niche": d.get("niche"),
        "product": d.get("product_type"),
        "price": d.get("price"),
        "score": s["score"],
        "manager_decision": s["manager_decision"],
        "coach": s["coach"],
        "user_override": run_over.get(did, "none"),
    })
df = pd.DataFrame(rows).sort_values("score", ascending=False)


def final_status(r):
    o, m = r["user_override"], r["manager_decision"]
    if o == "cancel" and m in ("GREENLIGHT", "HOLD"):
        return "CANCELED_BY_USER"
    if o == "force_approve" and m == "HOLD":
        return "FORCE_APPROVED"
    return {"GREENLIGHT": "PROCEEDS", "HOLD": "HELD", "BLOCK": "BLOCKED"}[m]


edited = st.data_editor(
    df,
    column_config={
        "user_override": st.column_config.SelectboxColumn("user_override", options=["none", "cancel", "force_approve"]),
    },
    disabled=[c for c in df.columns if c != "user_override"],
    hide_index=True,
    use_container_width=True,
    key=f"editor_{run}",
)

if st.button("Save overrides"):
    all_over[run] = {r.design_id: r.user_override for r in edited.itertuples() if r.user_override != "none"}
    OVERRIDES.write_text(json.dumps(all_over, indent=2))
    st.success("Overrides saved.")

edited["final_status"] = edited.apply(final_status, axis=1)
cols = st.columns(4)
for col, label in zip(cols, ["PROCEEDS", "HELD", "BLOCKED", "CANCELED_BY_USER"]):
    col.metric(label, int((edited["final_status"] == label).sum()))

st.subheader("What will actually proceed")
st.dataframe(edited[edited["final_status"].isin(["PROCEEDS", "FORCE_APPROVED"])], use_container_width=True)
st.caption("Even proceeding designs need explicit human approval before any real listing connector is used.")
