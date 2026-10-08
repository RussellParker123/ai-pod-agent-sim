"""Syncs paid Etsy orders to Printful for real fulfillment (print + ship).

Polls the shop's paid receipts, and for any receipt not yet forwarded,
creates a matching Printful order so Printful actually prints and ships the
physical product to the buyer. This is the only place that spends real
fulfillment money — it only ever acts on Etsy receipts that are already
confirmed paid, and each receipt is recorded so it's never double-submitted.
"""
from __future__ import annotations

import json
from typing import Dict, List, Optional

from app.integrations import etsy_client, printful_client
from app.integrations.config import DATA_DIR
from app.live.pipeline import list_all

PROCESSED_RECEIPTS_PATH = DATA_DIR / "processed_etsy_receipts.json"


def _load_processed() -> Dict[str, dict]:
    if PROCESSED_RECEIPTS_PATH.exists():
        with open(PROCESSED_RECEIPTS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def _save_processed(processed: Dict[str, dict]) -> None:
    PROCESSED_RECEIPTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(PROCESSED_RECEIPTS_PATH, "w", encoding="utf-8") as f:
        json.dump(processed, f, indent=2)


def _find_sync_variant_id(listing_id: int) -> Optional[int]:
    for entry in list_all():
        if entry.get("etsy_listing_id") == listing_id:
            product = entry.get("printful_sync_product") or {}
            variants = product.get("sync_variants") or []
            if variants:
                return variants[0].get("id")
    return None


def _receipt_to_recipient(receipt: dict) -> dict:
    return {
        "name": receipt.get("name", ""),
        "address1": receipt.get("first_line", ""),
        "address2": receipt.get("second_line") or "",
        "city": receipt.get("city", ""),
        "state_code": receipt.get("state", ""),
        "country_code": receipt.get("country_iso", ""),
        "zip": receipt.get("zip", ""),
        "email": receipt.get("buyer_email", ""),
    }


def sync_new_orders(confirm: bool = False) -> List[dict]:
    """Checks the connected Etsy shop for new paid receipts and places the
    corresponding Printful order for each one not already processed.

    `confirm`: forwarded to Printful — keep False (default) so orders land
    as Printful drafts requiring one more manual confirmation, layered on
    top of the fact that this only runs against already-paid Etsy orders.
    """
    me = etsy_client.get_me()
    shop_id = me["shop_id"]
    receipts = etsy_client.get_shop_receipts(shop_id, was_paid=True)

    processed = _load_processed()
    newly_synced = []

    for receipt in receipts:
        receipt_id = str(receipt["receipt_id"])
        if receipt_id in processed:
            continue

        items = []
        for txn in receipt.get("transactions", []):
            sync_variant_id = _find_sync_variant_id(txn["listing_id"])
            if sync_variant_id:
                items.append({"sync_variant_id": sync_variant_id, "quantity": txn.get("quantity", 1)})

        if not items:
            # Nothing we recognize (e.g. a listing not created through the
            # live pipeline) — skip rather than guess at fulfillment.
            continue

        order = printful_client.create_order_from_receipt(
            recipient=_receipt_to_recipient(receipt),
            items=items,
            etsy_receipt_id=receipt["receipt_id"],
            confirm=confirm,
        )
        processed[receipt_id] = {"printful_order_id": order.get("id"), "status": "forwarded"}
        newly_synced.append({"etsy_receipt_id": receipt["receipt_id"], "printful_order": order})

    _save_processed(processed)
    return newly_synced


if __name__ == "__main__":
    results = sync_new_orders()
    print(f"Forwarded {len(results)} new order(s) to Printful.")
    for r in results:
        print(r)
