"""Live Ops page: connection status, pending approvals, and the human
approval gate for publishing real Etsy listings / syncing real orders.

Nothing on this page auto-runs on page load except read-only status checks
and reading locally saved records. Every action that spends money, goes
public or calls Etsy requires an explicit button click here. Locally saved
records stay visible even when Etsy is not connected.
"""
import sys
import time
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

# Streamlit's multipage runner only puts the main script's directory (app/)
# on sys.path, not the repo root — so the "app" package itself isn't
# importable here unless we add the repo root ourselves.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from app.integrations import etsy_auth, openai_image, printful_client
from app.integrations.config import NotConfiguredError
from app.live import ops_state, order_sync, pipeline, recovery
from app.live_ops_presentation import (
    MANAGER_NODE,
    STAGE_NODES,
    STAGE_LOCATIONS,
    render_live_console,
    registry_counts,
    stage_status,
    entry_status,
)
from app.sim.characters import DrCypher

pipeline_recovery_note = recovery.RECOVERY_NOTE

st.title("Live Ops")
st.markdown(
    """<style>
    .stApp{background:linear-gradient(135deg,#0a0e27 0%,#1a1a3e 60%,#2d1b4e 100%);color:#e7f0ff}
    [data-testid="stSidebar"]{background:linear-gradient(135deg,#0a0e27,#1a1a3e);border-right:1px solid #00ff41}
    h1,h2,h3{color:#8cffaa;text-shadow:0 0 8px #00ff4159}
    [data-testid="metric-container"]{background:linear-gradient(135deg,#1a1a3e,#2d1b4e);
      border:1px solid #00ccff;border-radius:12px;padding:12px;box-shadow:0 0 12px #00ccff26}
    .live-hero{background:linear-gradient(135deg,#0a0e27,#1a1a3e 55%,#2d1b4e);border:2px solid #00ff41;
      border-radius:16px;padding:18px;text-align:center;box-shadow:0 0 22px #00ff4133;margin:4px 0 16px}
    .live-hero h2{margin:0;color:#00ff41;letter-spacing:clamp(1px,.5vw,4px)}
    .live-hero p{color:#00ccff;margin:8px 0 0}
    .cypher-panel{background:linear-gradient(135deg,#2d1b4e,#1a2d4e);border:2px solid #ff6b9d;
      border-radius:14px;padding:12px 16px;margin:10px 0 16px;text-align:center;box-shadow:0 0 16px #ff6b9d33}
    .cypher-panel strong{color:#ff6b9d}
    @media(prefers-reduced-motion:reduce){*,*::before,*::after{animation-duration:.01ms!important;animation-iteration-count:1!important;scroll-behavior:auto!important}}
    </style>
    <div class="live-hero"><h2>🎮 LIVE OPS ARENA 🎮</h2>
    <p>LIVE ETSY OPERATIONS · REAL STORE EVENTS, NOT A SIMULATION REPLAY</p></div>
    <div class="cypher-panel"><strong>🧪 DR. CYPHER · LIVE OPERATIONS OVERSEER</strong><br>
    Console states and registry counts are shown only when supported by actual live events or saved records.</div>""",
    unsafe_allow_html=True,
)

st.subheader("Connection status")
etsy_connected = etsy_auth.is_connected()
c1, c2, c3 = st.columns(3)
c1.metric("Etsy shop", "Connected" if etsy_connected else "Not connected",
          help="Based on a saved OAuth token file; the token is only verified with Etsy when you run an action.")
c2.metric("OpenAI (art)", "Configured" if openai_image.is_configured() else "Not configured")
c3.metric("Printful (fulfillment)", "Configured" if printful_client.is_configured() else "Not configured")

st.warning(
    "LIVE Etsy work: image generation may spend money. Creating a listing draft does not publish it publicly. "
    "If Manager auto-publish is enabled below, qualifying listings can be published automatically. "
    "Paid-order sync may initiate Printful fulfillment. No action runs on page load; use the explicit controls below."
)

if not etsy_connected:
    st.info(
        "Connect your Etsy shop first:\n\n"
        "    python -m app.setup.etsy_wizard --connect-etsy\n\n"
        "Actions that need Etsy (running a batch, publishing, staging drafts, order sync, Etsy reconciliation) "
        "are disabled until then. Your locally saved registry, image archive and recorded console history are "
        "still shown below."
    )


def _read_local(label, fn, default):
    """Read local records; on failure show a diagnostic instead of crashing
    or silently pretending the records are empty."""
    try:
        return fn(), None
    except pipeline.LocalStoreError as e:
        st.error(f"{label}: {e}")
        return default, str(e)


live_entries, registry_error = _read_local("Live listing registry", pipeline.list_all, [])
recorded_state, state_error = ops_state.load_state()
if state_error:
    st.error(state_error)
restored = ops_state.restored_view(recorded_state) if recorded_state else None
batch_running_here = bool(restored and restored["running_here"])

st.markdown("---")
st.subheader("Live Agent Pipeline · Event-Driven Operations Console")
k = st.number_input("How many designs to queue", min_value=1, max_value=20, value=6)
with st.expander("🎨 Art team settings (multiple AI artists per trending niche)"):
    st.caption(
        "The top N niches the trend/research agent scores highest each get their own small "
        "team of artist agents, each rendering the same niche in a different style, generated "
        "in parallel. Dr. Cypher (the manager agent) then picks the strongest variant(s) to "
        "actually list — more variants = more real OpenAI image spend."
    )
    team_niches = st.number_input("Niches that get an art team", min_value=0, max_value=5, value=2)
    team_size = st.number_input("Artists per team (style variants)", min_value=1, max_value=5, value=3)
with st.expander("🤖 Manager auto-publish (Dr. Cypher decides, you're the fallback)"):
    st.caption(
        "By default every design lands in Pending Approvals below and waits for you to click "
        "'Approve & publish live'. Turn this on to let Dr. Cypher (the manager agent) publish "
        "its own highest-confidence designs live on its own — anything below the confidence "
        "threshold still falls back to you for manual review, exactly like today."
    )
    manager_auto_publish = st.checkbox("Let Dr. Cypher auto-publish high-confidence designs", value=False)
    auto_publish_threshold = st.slider(
        "Manager confidence score required to auto-publish",
        min_value=0.5,
        max_value=1.0,
        value=0.85,
        step=0.01,
        disabled=not manager_auto_publish,
    )
run_blockers = []
if not etsy_connected:
    run_blockers.append("Etsy is not connected.")
if registry_error:
    run_blockers.append("the local listing registry can't be read (see the error above).")
if batch_running_here:
    run_blockers.append("a batch is already recorded as running in another session of this server.")
if restored and restored["batch"] and restored["batch"].get("display_status") == ops_state.INTERRUPTED:
    st.warning(
        "The last recorded batch was interrupted and has NOT been resumed or re-run. Before starting a new batch, "
        "check the registry below for drafts marked 'staging incomplete' (and your Etsy drafts) so you don't "
        "duplicate work. A new batch generates new designs; it never replays the old one."
    )
run_clicked = st.button(
    "▶ Run live batch (creates real Etsy DRAFT listings, not public)",
    disabled=bool(run_blockers),
    help=("Disabled: " + " ".join(run_blockers)) if run_blockers else None,
)

console_slot = st.empty()
stage_state = {key: "idle" for key, _, _ in STAGE_NODES + [MANAGER_NODE]}
log_lines: list = []
cypher_state = DrCypher().to_dict()
cypher_state["status"] = "idle"
if restored and not run_clicked:
    batch = restored["batch"] or {}
    if batch:
        status_text = {
            ops_state.COMPLETE: "completed",
            ops_state.FAILED: "failed",
            ops_state.INTERRUPTED: "was interrupted (server restart, page reload/stop, or crash) — not running",
            ops_state.RUNNING: "is running in another session of this server — this is a snapshot",
        }.get(batch.get("display_status"), "has an unknown status")
        detail = f" Queued {batch['queued_count']} design(s)." if batch.get("queued_count") is not None else ""
        error = f" Recorded error: {batch['error']}" if batch.get("error") else ""
        st.info(
            f"📼 Showing recorded history from disk, not live activity. Last batch {batch.get('batch_id')} "
            f"(started {batch.get('started_at')}) {status_text}.{detail}{error}"
        )
    with console_slot:
        components.html(
            render_live_console(restored["stage_state"], restored["log_lines"][-10:], restored["cypher"], recorded=True),
            height=560,
            scrolling=True,
        )
else:
    with console_slot:
        components.html(render_live_console(stage_state, log_lines, cypher_state), height=560, scrolling=True)

st.caption("🖼️ Live art feed — thumbnails appear here the instant each artist agent finishes a piece.")
gallery_slot = st.empty()
gallery: list = []
if restored and restored["gallery"] and not run_clicked:
    with gallery_slot.container():
        st.caption("Recorded art feed from the last batch (files on disk, not new activity).")
        recent = restored["gallery"][-6:]
        cols = st.columns(len(recent))
        for col, item in zip(cols, recent):
            if item["image_uri"]:
                col.image(item["image_uri"], caption=item["design_id"], width=110)
            else:
                col.caption(f"{item['design_id']}: image file missing")

if run_clicked:
    active_stage = None
    recorder = None
    try:
        recorder = ops_state.BatchRecorder(params={
            "k": int(k), "team_niches": int(team_niches), "team_size": int(team_size),
            "manager_auto_publish": bool(manager_auto_publish),
            "auto_publish_threshold": float(auto_publish_threshold),
        })
        queued = []
        for event in pipeline.run_live_batch_stream(
            k=int(k),
            team_niches=int(team_niches),
            team_size=int(team_size),
            manager_auto_publish=manager_auto_publish,
            auto_publish_threshold=auto_publish_threshold,
        ):
            stage = str(event["stage"])
            if stage == "complete":
                queued = event["queued"]
                for key, value in stage_state.items():
                    if value == "active":
                        stage_state[key] = "done"
                cypher_state["status"] = "done"
                cypher_state["activity"] = "Live batch complete"
                cypher_state["location"] = cypher_state["home"]
                message = f"Live batch complete — {len(queued)} design(s) saved to the registry."
                log_lines.append(f"> [complete] {message}")
                recorder.record({"stage": "complete", "status": "done", "message": message}, stage_state, cypher_state)
                with console_slot:
                    components.html(
                        render_live_console(stage_state, log_lines[-10:], cypher_state),
                        height=560,
                        scrolling=True,
                    )
                continue
            if stage in stage_state:
                stage_state[stage] = stage_status({stage: event.get("status")}, stage)
                active_stage = stage if stage_state[stage] == "active" else (
                    None if active_stage == stage else active_stage
                )
            if isinstance(event.get("character"), dict):
                cypher_state.update(DrCypher.from_dict(event["character"]).to_dict())
            cypher_state["status"] = "active"
            cypher_state["location"] = STAGE_LOCATIONS.get(stage, cypher_state["location"])
            if not isinstance(event.get("character"), dict):
                cypher_state["activity"] = str(event.get("message", ""))
                cypher_state["line"] = cypher_state["activity"]
            log_lines.append(f"> [{stage}] {event['message']}")
            with console_slot:
                components.html(
                    render_live_console(stage_state, log_lines[-10:], cypher_state),
                    height=560,
                    scrolling=True,
                )

            image_uri = event.get("image_uri")
            gallery_item = None
            if image_uri and not image_uri.startswith("sim://") and Path(image_uri).exists():
                gallery_item = {"design_id": str(event["design_id"]), "image_uri": str(image_uri)}
            recorder.record(event, stage_state, cypher_state, gallery_item)
            if gallery_item:
                gallery.append((event["design_id"], image_uri))
                with gallery_slot:
                    recent = gallery[-6:]
                    cols = st.columns(len(recent))
                    for col, (design_id, path) in zip(cols, recent):
                        col.image(path, caption=design_id, width=110)

            time.sleep(0.25)  # just pacing for readability — every event above is real work already done
        recorder.finish(ops_state.COMPLETE, queued_count=len(queued), stage_state=stage_state, cypher=cypher_state)
        st.success(f"Queued {len(queued)} design(s) for approval.")
    except NotConfiguredError as e:
        cypher_state.update(
            status="error",
            mood="exasperated",
            activity="Live operations halted",
            line=str(e),
        )
        if active_stage:
            stage_state[active_stage] = "error"
            with console_slot:
                components.html(
                    render_live_console(stage_state, log_lines[-10:], cypher_state),
                    height=560,
                    scrolling=True,
                )
        if recorder:
            recorder.finish(ops_state.FAILED, error=str(e), stage_state=stage_state, cypher=cypher_state)
        st.error(str(e))
    except Exception as e:  # noqa: BLE001 - surface any live-pipeline error to the operator
        cypher_state.update(
            status="error",
            mood="exasperated",
            activity="Live operations halted",
            line=f"Live batch failed: {e}",
        )
        if active_stage:
            stage_state[active_stage] = "error"
            with console_slot:
                components.html(
                    render_live_console(stage_state, log_lines[-10:], cypher_state),
                    height=560,
                    scrolling=True,
                )
        if recorder:
            recorder.finish(ops_state.FAILED, error=f"Live batch failed: {e}", stage_state=stage_state,
                            cypher=cypher_state)
        st.error(f"Live batch failed: {e}")
        st.caption("Any Etsy drafts created before the failure are already saved in the registry below "
                   "(possibly as 'staging incomplete'). Nothing is retried automatically.")
    finally:
        # A Streamlit rerun/stop raises a non-Exception control-flow signal
        # mid-batch; record that honestly instead of leaving it "running".
        if recorder and not recorder.finished:
            recorder.finish(ops_state.INTERRUPTED, error="Run stopped before completion (page rerun/stop).",
                            stage_state=stage_state, cypher=cypher_state)

st.markdown("---")
if run_clicked:
    live_entries, registry_error = _read_local("Live listing registry", pipeline.list_all, [])
auto_published = [e for e in live_entries if e.get("published_by") == "manager"]
if auto_published:
    st.subheader("🤖 Auto-published by Dr. Cypher")
    st.caption("These went live automatically — no human click — because the Manager's score met your threshold.")
    for entry in auto_published[-10:]:
        st.write(f"✅ **{entry['design_id']}** — {entry['niche']} (${entry['price']}) — listing_id={entry['etsy_listing_id']}")

st.markdown("---")
st.subheader("📋 Live listing registry")
st.caption(
    "Read-only summary of locally saved live pipeline records. Draft, published, and rejected labels come "
    "from each stored record; listing prices are not sales and no revenue/profit is reported here."
)
status_counts = registry_counts(live_entries)
registry_cols = st.columns(5)
registry_cols[0].metric("📝 Drafts · awaiting review", status_counts["drafts"])
registry_cols[1].metric("🌐 Published", status_counts["published"])
registry_cols[2].metric("⛔ Rejected", status_counts["rejected"])
registry_cols[3].metric("⚠️ Incomplete / recovered / other", status_counts["other"])
registry_cols[4].metric("📦 Recorded entries", len(live_entries))
if registry_error:
    st.warning("The registry file exists but couldn't be read, so no records are listed. It was not modified.")
elif not live_entries:
    st.info("No live listing records have been saved yet.")
else:
    for entry in reversed(live_entries):
        design_id = str(entry.get("design_id") or "Design")
        niche = str(entry.get("niche") or "Niche not recorded")
        product_type = str(entry.get("product_type") or "Product not recorded")
        with st.expander(f"{design_id} · {entry_status(entry)} · {niche} ({product_type})"):
            st.caption(f"Status: {entry_status(entry)}")
            if entry.get("etsy_listing_id") is not None:
                st.caption(f"Etsy listing ID: {entry['etsy_listing_id']}")
            if entry.get("published_by"):
                st.caption(f"Published by: {entry['published_by']}")
            if entry.get("manager_score") is not None:
                st.caption(f"Recorded manager score: {entry['manager_score']}")
            if entry.get("compliance_status"):
                st.caption(f"Recorded compliance status: {entry['compliance_status']}")
            if entry.get("rejection_reason"):
                st.caption(f"Recorded rejection reason: {entry['rejection_reason']}")
            if entry.get("status") == pipeline.STAGING_INCOMPLETE:
                st.warning(
                    f"The Etsy draft exists but staging stopped after step '{entry.get('staging_step')}'. "
                    "It is not publishable or fulfillable from this app and is not retried automatically; "
                    "review it in Etsy."
                )
            if entry.get("staging_error"):
                st.caption(f"Recorded staging error: {entry['staging_error']}")
            if entry.get("publish_error"):
                st.caption(f"Recorded publish error (draft remains): {entry['publish_error']}")
            if entry.get("recovered"):
                rec = entry["recovered"]
                st.info(
                    f"{pipeline_recovery_note} Etsy state at import: {rec.get('etsy_state')}; "
                    f"title: {rec.get('etsy_title')!r}; imported {rec.get('imported_at')}."
                )

st.markdown("---")
st.subheader("Pending approvals")
pending, _ = _read_local("Pending approvals", pipeline.list_pending, [])
if not etsy_connected:
    st.caption("Publishing is disabled until Etsy is connected. Rejecting is local and stays available.")
if not pending:
    st.info("Nothing pending. Run a live batch above.")
else:
    for i, entry in enumerate(pending):
        with st.expander(f"{entry['design_id']} — {entry['niche']} ({entry['product_type']}) — ${entry['price']}"):
            mockup_uri = entry.get("mockup_image_uri")
            if mockup_uri and Path(mockup_uri).exists():
                st.image(mockup_uri, width=300)
            elif entry.get("etsy_image_url"):
                st.image(entry["etsy_image_url"], width=300)
            st.write(entry["prompt"])
            concept = (entry.get("quality") or {}).get("concept") or {}
            image_check = (entry.get("quality") or {}).get("image") or {}
            if concept:
                st.caption(f"Concept pre-check (text only): {concept.get('status')} · issues: "
                           + ("; ".join(concept.get("issues") or []) or "none"))
            if image_check:
                st.caption(f"Generated-image assessment: {image_check.get('status')} — {image_check.get('reason', '')}")
            if entry.get("source") == "recycling":
                st.info("Recycled reuse candidate (existing image, fresh gates). Lineage: "
                        + ", ".join(f"{k}={v}" for k, v in (entry.get("lineage") or {}).items()
                                    if k != "original_rejection"))
            st.caption(f"Etsy draft listing_id={entry['etsy_listing_id']} — waiting on your review (below Dr. Cypher's auto-publish threshold)")
            reject_reason = st.text_input(
                "Rejection reason (kept with the image in the Recycling Facility)",
                value="rejected by human reviewer", key=f"reason_{i}_{entry['design_id']}",
            )
            col_a, col_r = st.columns(2)
            if col_a.button("Approve & publish live", key=f"approve_{i}_{entry['design_id']}",
                            disabled=not etsy_connected):
                pipeline.approve_and_publish(entry["design_id"])
                st.success("Published.")
                st.rerun()
            if col_r.button("Reject", key=f"reject_{i}_{entry['design_id']}"):
                rejected = pipeline.reject(entry["design_id"], reason=reject_reason.strip()[:300] or "rejected")
                st.warning(f"Rejected. Image sent to the Recycling Facility (record {rejected.get('recycling_record_id')}).")
                st.rerun()

st.markdown("---")
st.subheader("🖼️ Image archive")
st.caption(
    "Every real OpenAI image ever generated, including anything from before this batch, "
    "with the Manager's score/decision when it's known. Nothing is ever deleted locally — "
    "if a batch failed or a design never got approved, the art is still sitting right here "
    "and the raw file is reusable."
)
try:
    archive = pipeline.list_image_archive()
except pipeline.LocalStoreError as e:
    st.error(f"Image manifest: {e}")
    st.warning("Showing every image file on disk without its recorded metadata (scores/niches unavailable).")
    archive = pipeline.list_orphan_images()
if not archive:
    st.info("No images generated yet.")
else:
    st.caption(f"{len(archive)} image(s) on disk in data/images/.")
    unscored = sum(1 for e in archive if e.get("manager_score") is None)
    if unscored:
        st.warning(
            f"{unscored} of these were generated before score-tracking was added (or by a run that crashed "
            "before completing) — no niche/score was recorded for them, so there's no way to know in "
            "hindsight whether the Manager would've greenlit them. You can still open the files directly "
            "in data/images/ and reuse any you like for a manual listing."
        )
    sorted_archive = sorted(archive, key=lambda e: (e.get("manager_score") is None, -(e.get("manager_score") or 0)))
    already_staged = {e.get("design_id") for e in live_entries}
    cols = st.columns(4)
    for i, entry in enumerate(sorted_archive):
        with cols[i % 4]:
            st.image(entry["image_uri"], use_column_width=True)
            score = entry.get("manager_score")
            decision = entry.get("manager_decision")
            if score is not None:
                st.caption(f"**{entry['design_id']}** — {entry.get('niche') or '?'}\nscore {score} ({decision})")
            else:
                st.caption(f"**{entry['design_id']}** — no score recorded")

            if st.button("♻️ Hold for reuse", key=f"hold_{entry['design_id']}",
                         help="Send to the Recycling Facility for a metadata cross-reference (no new image)."):
                try:
                    record = pipeline.hold_archive_image_for_reuse(entry["design_id"])
                    st.success(f"In the Recycling Facility as {record['record_id']} ({record['status']}).")
                except ValueError as e:
                    st.error(str(e))
            if entry["design_id"] in already_staged:
                st.caption("✅ already staged")
            else:
                with st.expander("♻️ Stage as Etsy draft"):
                    st.caption("No new image is generated — this reuses the file you already paid for.")
                    with st.form(key=f"stage_form_{entry['design_id']}"):
                        niche_in = st.text_input("Niche", value=entry.get("niche") or "", key=f"niche_{entry['design_id']}")
                        product_in = st.selectbox(
                            "Product type", ["mug", "tshirt", "tote"],
                            index=["mug", "tshirt", "tote"].index(entry["product_type"]) if entry.get("product_type") in ("mug", "tshirt", "tote") else 0,
                            key=f"product_{entry['design_id']}",
                        )
                        price_in = st.number_input(
                            "Price ($)", min_value=0.01, value=float(entry.get("price") or 15.0),
                            step=0.5, key=f"price_{entry['design_id']}",
                        )
                        desc_in = st.text_area(
                            "Listing description", value=entry.get("prompt") or "", key=f"desc_{entry['design_id']}",
                        )
                        submitted = st.form_submit_button(
                            "Create Etsy draft from this image", disabled=not etsy_connected or bool(registry_error)
                        )
                    if submitted:
                        if not niche_in.strip() or not desc_in.strip():
                            st.error("Niche and description are required.")
                        else:
                            try:
                                pipeline.stage_archived_image(
                                    design_id=entry["design_id"],
                                    image_uri=entry["image_uri"],
                                    niche=niche_in.strip(),
                                    product_type=product_in,
                                    price=float(price_in),
                                    description=desc_in.strip(),
                                )
                                st.success(f"Staged {entry['design_id']} as a new Etsy draft — check Pending approvals below.")
                                st.rerun()
                            except Exception as e:  # noqa: BLE001
                                st.error(f"Failed to stage: {e}")

st.markdown("---")
st.subheader("Order fulfillment sync")
st.caption(
    "Checks your Etsy shop for new PAID orders and forwards them to Printful to "
    "actually print and ship. Only acts on confirmed paid receipts."
)
if st.button("Sync new paid orders to Printful", disabled=not etsy_connected):
    if not printful_client.is_configured():
        st.error("PRINTFUL_API_KEY is not set yet — add it to .env first.")
    else:
        with st.spinner("Checking Etsy receipts..."):
            try:
                results = order_sync.sync_new_orders()
                st.success(f"Forwarded {len(results)} new order(s) to Printful.")
                for r in results:
                    st.json(r)
            except Exception as e:  # noqa: BLE001
                st.error(f"Order sync failed: {e}")
