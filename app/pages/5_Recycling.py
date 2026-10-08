"""Recycling Facility: rejected images that already exist, the recycler
agent's metadata cross-reference, and explicit human review actions.

Nothing on this page generates images, spends money or publishes. A reuse
request creates a new candidate that must pass the current compliance,
quality, pricing and Manager gates and your explicit approval (Review page
for simulation runs, Live Ops for live Etsy drafts)."""
import json
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from app.sim import recycling  # noqa: E402

DATA_DIR = _REPO_ROOT / "data"
IMAGES_DIR = DATA_DIR / "images"
STORE_PATH = DATA_DIR / recycling.RECYCLING_FILENAME

st.title("♻️ Recycling Facility")
st.caption(
    "Rejected art that already has an image is delivered here with its source design, original niche/product/"
    "prompt, rejection reason, compliance and provenance. The recycler agent cross-references metadata only "
    "(it does not look at pixels) and suggests alternate uses. Compliance-flagged assets are quarantined. "
    "Concept-only rejections never had an image and are not queued; nothing here generates new images."
)

store = recycling.RecyclingStore(STORE_PATH)
records = store.records
groups = recycling.outcome_counts(records)
c = st.columns(5)
c[0].metric("In facility", len(records))
c[1].metric("Pending reuse review", groups["pending_reuse"])
c[2].metric("Quarantined", groups["quarantined"])
c[3].metric("Unusable / archived", groups["unusable"])
c[4].metric("Reuse requested", store.counts().get(recycling.REUSE_REQUESTED, 0))

if not records:
    st.info("Nothing in the facility yet. Manager-blocked images from simulation runs, images you reject in "
            "Live Ops, designs you cancel on the Review page, and archive images you 'Hold for reuse' land here.")
    st.stop()


def _latest_context():
    runs = sorted(DATA_DIR.glob("run_*.json"))
    research, approved = {}, []
    if runs:
        try:
            payload = json.loads(runs[-1].read_text(encoding="utf-8"))
            research = payload.get("research") or {}
            approved = [d for d in payload.get("designs", []) if d.get("approved")]
        except (OSError, ValueError):
            pass
    archive = []
    manifest = DATA_DIR / "image_manifest.json"
    if manifest.exists():
        try:
            archive = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            archive = []
    return recycling.build_context(research=research, approved_designs=approved,
                                   archive=archive if isinstance(archive, list) else [])


status_filter = st.multiselect("Status", list(recycling.STATUSES),
                               default=[s for s in recycling.STATUSES if s not in (recycling.ARCHIVED,)])
source_filter = st.multiselect("Source", sorted({r["source"] for r in records}),
                               default=sorted({r["source"] for r in records}))
shown = [r for r in records if r["status"] in status_filter and r["source"] in source_filter]
st.dataframe(pd.DataFrame([{
    "record": r["record_id"], "design": r["source_design_id"], "source": r["source"], "status": r["status"],
    "niche": r["original"].get("niche"), "product": r["original"].get("product_type"),
    "rejected_by": r["rejection"]["by"], "reason": r["rejection"]["reason"],
    "top suggestion": ((r.get("analysis") or {}).get("suggestions") or [{}])[0].get("type"),
} for r in shown]), hide_index=True, use_container_width=True)


def _act(fn, *args, **kwargs):
    try:
        result = fn(*args, **kwargs)
        store.save()
        st.rerun()
        return result
    except (recycling.RecyclingError, ValueError) as exc:
        st.error(str(exc))


for r in shown:
    rid = r["record_id"]
    with st.expander(f"{rid} · {r['source_design_id']} · {r['status']}"):
        left, right = st.columns([1, 2])
        with left:
            local = recycling.safe_image_path(r["image_uri"], IMAGES_DIR)
            if local is not None:
                st.image(str(local), caption="original image (unchanged)", use_column_width=True)
            elif r["image_uri"].startswith("sim://"):
                st.caption("Simulated asset: no image pixels exist for this run.")
            else:
                st.caption("Original file not found under data/images/ — preview unavailable.")
            st.text(f"image: {r['image_uri']}")
        with right:
            st.text(f"Original: {r['original'].get('niche')} on {r['original'].get('product_type')} "
                    f"(${r['original'].get('price')})")
            st.text(f"Rejected by {r['rejection']['by']} at {r['rejection'].get('stage') or '?'}: "
                    f"{r['rejection']['reason']}")
            st.text(f"Compliance: {r['compliance']['status']} {r['compliance'].get('notes') or ''}")
            st.text("Prompt: " + str(r["original"].get("prompt") or ""))
            st.text("Provenance: " + json.dumps(r.get("provenance") or {}))
            if r.get("lineage"):
                st.text("Lineage: " + json.dumps(r["lineage"]))

        analysis = r.get("analysis") or {}
        if analysis:
            st.markdown(f"**Recycler analysis** by `{analysis.get('recycler_id')}` · method "
                        f"`{analysis.get('method')}` · image inspected: **{analysis.get('image_inspected')}**")
            st.caption(analysis.get("limitations", ""))
            st.dataframe(pd.DataFrame([{
                "id": s["suggestion_id"], "type": s["type"], "niche": s.get("target_niche"),
                "product": s.get("target_product"), "confidence": s["confidence"],
                "reasons": " | ".join(s["reasons"]), "references": ", ".join(s["references"]),
            } for s in analysis.get("suggestions", [])]), hide_index=True, use_container_width=True)
        else:
            st.caption("Not analysed yet.")

        if r.get("reuse"):
            st.text("Reuse request: " + json.dumps(r["reuse"]))

        a1, a2, a3, a4 = st.columns(4)
        can_analyze = (r["status"] in (recycling.PENDING_ANALYSIS, recycling.PENDING_REVIEW, recycling.QUARANTINED)
                       and r["analysis_attempts"] < recycling.MAX_ANALYSIS_ATTEMPTS)
        if a1.button("🔁 Re-analyze", key=f"an_{rid}", disabled=not can_analyze,
                     help=f"Metadata cross-reference, max {recycling.MAX_ANALYSIS_ATTEMPTS} attempts"):
            _act(store.analyze, rid, _latest_context(), images_root=IMAGES_DIR)
        options = [s for s in analysis.get("suggestions", []) if s["type"] in recycling.REUSABLE_TYPES]
        if r["status"] == recycling.PENDING_REVIEW and options:
            pick = a2.selectbox("Suggestion", [s["suggestion_id"] for s in options], key=f"pick_{rid}",
                                format_func=lambda sid: next(f"{s['type']} → {s.get('target_niche')} / "
                                                             f"{s.get('target_product')} ({s['confidence']})"
                                                             for s in options if s["suggestion_id"] == sid))
            if a2.button("♻️ Request reuse", key=f"reuse_{rid}"):
                _act(store.review, rid, "request_reuse", suggestion_id=pick)
        if a3.button("🗄 Archive", key=f"arch_{rid}", disabled=r["status"] in (recycling.ARCHIVED, recycling.REENTERED)):
            _act(store.review, rid, "archive")
        if a4.button("🚫 Mark unusable", key=f"unus_{rid}",
                     disabled=r["status"] in (recycling.UNUSABLE, recycling.REENTERED)):
            _act(store.review, rid, "mark_unusable")

        if r["status"] == recycling.REUSE_REQUESTED:
            if r["source"] == "simulation":
                st.info("Will re-enter the next simulation run as a new candidate (same image, fresh compliance, "
                        "quality, pricing and Manager gates), then wait for your approval on the Review page.")
            elif r["asset_kind"] == "generated_image":
                st.caption("Creates a new Etsy DRAFT using the existing image after fresh gates. Not published; "
                           "approve it in Live Ops. No new image is generated.")
                if st.button("Run gates & stage as Etsy draft", key=f"stage_{rid}"):
                    try:
                        from app.live import pipeline

                        result = pipeline.stage_recycled_candidate(rid)
                        st.write({"status": result["status"], "gates": result.get("gates")})
                    except Exception as exc:  # noqa: BLE001 - surface integration errors to the operator
                        st.error(f"Could not stage: {exc}")

        with st.popover("History") if hasattr(st, "popover") else st.container():
            st.dataframe(pd.DataFrame(r["history"]).astype(str), hide_index=True, use_container_width=True)
