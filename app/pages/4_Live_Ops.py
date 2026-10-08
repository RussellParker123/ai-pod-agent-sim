"""Live Ops page: connection status, pending approvals, and the human
approval gate for publishing real Etsy listings / syncing real orders.

Nothing on this page auto-runs on page load except read-only status checks.
Every action that spends money or goes public requires an explicit button
click here.
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
from app.live import order_sync, pipeline

st.title("Live Ops")

st.subheader("Connection status")
c1, c2, c3 = st.columns(3)
c1.metric("Etsy shop", "Connected" if etsy_auth.is_connected() else "Not connected")
c2.metric("OpenAI (art)", "Configured" if openai_image.is_configured() else "Not configured")
c3.metric("Printful (fulfillment)", "Configured" if printful_client.is_configured() else "Not configured")

if not etsy_auth.is_connected():
    st.info(
        "Connect your Etsy shop first:\n\n"
        "    python -m app.setup.etsy_wizard --connect-etsy"
    )
    st.stop()

# --- Cyberpunk ops console --------------------------------------------------
# Same agents as the simulation's "Office" page (app/sim/agents.py,
# app/sim/manager.py), driven live by app.live.pipeline.run_live_batch_stream()
# — the only differences from simulation are real OpenAI art generation and
# two extra real-world stages (deploying to Etsy, syncing to Printful).
STAGE_NODES = [
    ("etsy_connect", "📡", "ETSY UPLINK"),
    ("trend", "📈", "TREND SCANNER"),
    ("prompt", "⌨️", "PROMPT FORGE"),
    ("image", "🖼️", "ART SYNTH // OPENAI"),
    ("compliance", "🛡️", "COMPLIANCE DAEMON"),
    ("mockup", "🧵", "MOCKUP RENDER"),
    ("pricing", "💠", "PRICE CORE"),
    ("manager", "🧠", "MANAGER AI"),
    ("etsy", "🛰️", "ETSY DEPLOY"),
    ("printful", "🏭", "PRINTFUL FAB LINK"),
]

CYBER_CSS = """
<style>
  .cyber-wrap{background:#05060a;border:1px solid #1d2a33;border-radius:10px;padding:16px;
    font-family:'Courier New',monospace;
    background-image:
      linear-gradient(rgba(0,255,242,.04) 1px, transparent 1px),
      linear-gradient(90deg, rgba(0,255,242,.04) 1px, transparent 1px);
    background-size:24px 24px;}
  .cyber-title{color:#00fff2;letter-spacing:3px;font-size:13px;margin-bottom:10px;
    text-shadow:0 0 6px #00fff2aa;}
  .cyber-grid{display:grid;grid-template-columns:repeat(5,1fr);gap:10px;margin-bottom:12px;}
  .node{border:1px solid #2a3b44;border-radius:8px;padding:10px 6px;text-align:center;
    background:rgba(10,14,20,.8);transition:all .25s;}
  .node .icon{font-size:22px;}
  .node .label{font-size:10px;color:#6fa3ad;letter-spacing:1px;margin-top:4px;}
  .node .dot{display:inline-block;width:7px;height:7px;border-radius:50%;margin-top:6px;background:#2a3b44;}
  .node.active{border-color:#ff2bd6;box-shadow:0 0 14px 2px #ff2bd699;animation:pulse 0.9s infinite;}
  .node.active .label{color:#ff6bf0;}
  .node.active .dot{background:#ff2bd6;box-shadow:0 0 8px 2px #ff2bd6;}
  .node.done{border-color:#00ff8c;}
  .node.done .label{color:#5effc0;}
  .node.done .dot{background:#00ff8c;box-shadow:0 0 6px 1px #00ff8c;}
  @keyframes pulse{0%,100%{transform:scale(1)}50%{transform:scale(1.04)}}
  .term{background:#000;border:1px solid #1d2a33;border-radius:6px;padding:8px 10px;height:150px;
    overflow-y:auto;font-size:12px;color:#00ff8c;}
  .term .line{opacity:.9;}
  .term .line.active{color:#ff6bf0;}
</style>
"""


def _cyber_html(stage_state: dict, log_lines: list) -> str:
    nodes = ""
    for key, icon, label in STAGE_NODES:
        cls = "node " + stage_state.get(key, "idle")
        nodes += f'<div class="{cls}"><div class="icon">{icon}</div><div class="label">{label}</div><div class="dot"></div></div>'
    log_html = "".join(f'<div class="line">{line}</div>' for line in log_lines) or '<div class="line">&gt; standing by...</div>'
    return (
        CYBER_CSS
        + '<div class="cyber-wrap">'
        + '<div class="cyber-title">⚡ NEURALARTTREASURES // LIVE OPS CONSOLE ⚡</div>'
        + f'<div class="cyber-grid">{nodes}</div>'
        + f'<div class="term">{log_html}</div>'
        + "</div>"
    )


st.markdown("---")
st.subheader("Live Agent Pipeline")
k = st.number_input("How many designs to queue", min_value=1, max_value=20, value=6)
run_clicked = st.button("▶ Run live batch (creates real Etsy DRAFT listings, not public)")

console_slot = st.empty()
stage_state = {key: "idle" for key, _, _ in STAGE_NODES}
log_lines: list = []
with console_slot:
    components.html(_cyber_html(stage_state, log_lines), height=280)

if run_clicked:
    try:
        queued = []
        for event in pipeline.run_live_batch_stream(k=int(k)):
            if event["stage"] == "complete":
                queued = event["queued"]
                continue
            stage_state[event["stage"]] = event["status"]
            log_lines.append(f"&gt; [{event['stage']}] {event['message']}")
            with console_slot:
                components.html(_cyber_html(stage_state, log_lines[-10:]), height=280)
            time.sleep(0.35)  # just pacing for readability — every event above is real work already done
        st.success(f"Queued {len(queued)} design(s) for approval.")
    except NotConfiguredError as e:
        st.error(str(e))
    except Exception as e:  # noqa: BLE001 - surface any live-pipeline error to the operator
        st.error(f"Live batch failed: {e}")

st.markdown("---")
st.subheader("Pending approvals")
pending = pipeline.list_pending()
if not pending:
    st.info("Nothing pending. Run a live batch above.")
else:
    for entry in pending:
        with st.expander(f"{entry['design_id']} — {entry['niche']} ({entry['product_type']}) — ${entry['price']}"):
            if entry.get("etsy_image_url"):
                st.image(entry["etsy_image_url"], width=300)
            st.write(entry["prompt"])
            st.caption(f"Etsy draft listing_id={entry['etsy_listing_id']}")
            col_a, col_r = st.columns(2)
            if col_a.button("Approve & publish live", key=f"approve_{entry['design_id']}"):
                pipeline.approve_and_publish(entry["design_id"])
                st.success("Published.")
                st.rerun()
            if col_r.button("Reject", key=f"reject_{entry['design_id']}"):
                pipeline.reject(entry["design_id"])
                st.warning("Rejected.")
                st.rerun()

st.markdown("---")
st.subheader("Order fulfillment sync")
st.caption(
    "Checks your Etsy shop for new PAID orders and forwards them to Printful to "
    "actually print and ship. Only acts on confirmed paid receipts."
)
if st.button("Sync new paid orders to Printful"):
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
