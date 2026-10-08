"""Live Ops page: connection status, pending approvals, and the human
approval gate for publishing real Etsy listings / syncing real orders.

Nothing on this page auto-runs on page load except read-only status checks.
Every action that spends money or goes public requires an explicit button
click here.
"""
import streamlit as st

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

st.markdown("---")
st.subheader("Generate a new live batch")
k = st.number_input("How many designs to queue", min_value=1, max_value=20, value=6)
if st.button("Run live batch (creates Etsy DRAFT listings, not public)"):
    with st.spinner("Generating designs, creating draft listings..."):
        try:
            queued = pipeline.run_live_batch(k=int(k))
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
