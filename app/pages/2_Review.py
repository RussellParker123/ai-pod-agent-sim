"""Review page: approve, cancel, or override manager decisions.

Overrides are saved to data/overrides.json and never alter the original run file.
- approve:        explicitly approve a GREENLIGHT design for publishing
- cancel:         stop a design the manager passed (GREENLIGHT or HOLD)
- force_approve:  push a HOLD design through. Compliance-blocked designs can NOT be forced.
"""
import json
import pandas as pd
import streamlit as st
from app.sim import recycling
from app.sim.approvals import final_review_status

from app.paths import DATA_DIR  # honours AI_POD_DATA_DIR like the rest of the app
OVERRIDES = DATA_DIR / "overrides.json"
RECYCLING_PATH = DATA_DIR / recycling.RECYCLING_FILENAME

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
        "reasons": "; ".join(s.get("reasons") or []),
        "concept_check": s.get("concept_check", "n/a"),
        "recycled_from": (d.get("lineage") or {}).get("recycled_from", ""),
        "user_override": run_over.get(did, "none"),
    })
df = pd.DataFrame(rows).sort_values("score", ascending=False)

st.subheader("Marketing & search visibility")
marketing_id = st.selectbox("Review marketing draft for design", df["design_id"].tolist())
marketing = designs.get(marketing_id, {}).get("marketing") or {}
if marketing:
    st.text(marketing["title"])
    st.text(marketing["description"])
    st.text("Suggested keywords: " + ", ".join(marketing["keywords"]))
    st.text("Etsy tags: " + ", ".join(marketing["tags"]))
    st.text("Image alt text draft: " + marketing["image_alt_text"])
    for recommendation in marketing["recommendations"]:
        st.text("- " + recommendation)
    st.caption(marketing["limitations"])
else:
    st.info("No marketing draft: older run, disabled marketing department, or compliance/product details need review.")


st.subheader("Art quality & reviewer feedback")
quality_id = st.selectbox("Inspect art brief and checks for design", df["design_id"].tolist(), key="quality_pick")
qd = designs.get(quality_id, {})
quality = qd.get("quality") or {}
concept = quality.get("concept") or {}
image_check = quality.get("image") or {}
if qd.get("brief"):
    st.caption("Concept pre-check = text-only review of the brief/prompt before any image. It does not inspect "
               "pixels or establish legal safety.")
    st.json(qd["brief"], expanded=False)
    st.text("Prompt: " + str(qd.get("prompt", "")))
    if concept.get("checks"):
        st.dataframe(pd.DataFrame(concept["checks"]).astype(str), hide_index=True, use_container_width=True)
    st.text(f"Concept pre-check: {concept.get('status', 'n/a')} (score {concept.get('score', 'n/a')})")
    st.text(f"Generated-image assessment: {image_check.get('status', 'n/a')} — {image_check.get('reason', '')}")
    if qd.get("review_history"):
        st.markdown("**Review history (what changed and why)**")
        st.dataframe(pd.DataFrame(qd["review_history"]).astype(str), hide_index=True, use_container_width=True)
    if qd.get("lineage"):
        st.info("Recycled reuse candidate — needs your explicit approval like any other design. Lineage: "
                + json.dumps(qd["lineage"]))
else:
    st.info("Older run: no structured brief or quality checks recorded.")


def final_status(r):
    design = designs.get(r["design_id"], {})
    return final_review_status(
        r["manager_decision"], design.get("compliance_status", "pending"), r["user_override"]
    )


edited = st.data_editor(
    df,
    column_config={
        "user_override": st.column_config.SelectboxColumn(
            "user_override", options=["none", "approve", "cancel", "force_approve"]
        ),
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
    canceled = [d for d, action in all_over[run].items() if action == "cancel"]
    if canceled:
        store = recycling.RecyclingStore(RECYCLING_PATH)
        context = recycling.build_context(
            research=payload.get("research"),
            approved_designs=[d for d in payload["designs"] if d.get("approved")],
        )
        summary = recycling.enqueue_human_rejections(store, run, payload["designs"], canceled, context)
        store.save()
        st.info(f"Recycling Facility: {len(summary['created'])} canceled image(s) queued, "
                f"{len(summary['duplicate'])} already queued, {len(summary['skipped_no_image'])} had no image.")

edited["final_status"] = edited.apply(final_status, axis=1)
cols = st.columns(5)
for col, label in zip(
    cols, ["APPROVED", "FORCE_APPROVED", "PENDING_REVIEW", "BLOCKED", "CANCELED_BY_USER"]
):
    col.metric(label, int((edited["final_status"] == label).sum()))

st.subheader("What will actually proceed")
st.dataframe(
    edited[edited["final_status"].isin(["APPROVED", "FORCE_APPROVED"])],
    use_container_width=True,
)
st.caption("Run `python -m app.sim.run_simulation --publish-run <run_file> --real` to list only explicitly approved designs.")
