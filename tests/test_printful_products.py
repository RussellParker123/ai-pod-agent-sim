from unittest.mock import Mock

import pytest

from app.integrations import printful_client
from app.live import pipeline
from app.live.catalog_map import (
    PRODUCT_CATALOG_DETAILS,
    PRODUCT_PRINTFUL_PRODUCT,
    PRODUCT_PRINTFUL_VARIANT,
    PRODUCT_UNIT_COSTS,
)
from app.marketplace.adapter import EtsyAdapter
from app.sim.agents import Design, mockup_agent, pricing_agent
from app.sim.marketing import marketing_agent


TOTE_NAME = "Eco Tote Bag | Econscious EC8000"


@pytest.mark.parametrize(
    "product_type,product_id,variant_id,cost",
    [("tote", 367, 10457, 15.87), ("mug", 19, 1320, 6.07), ("tshirt", 71, 4012, 11.92)],
)
def test_catalog_selection_and_base_cost(product_type, product_id, variant_id, cost):
    assert PRODUCT_PRINTFUL_PRODUCT[product_type] == product_id
    assert PRODUCT_PRINTFUL_VARIANT[product_type] == variant_id
    assert PRODUCT_UNIT_COSTS[product_type] == cost
    design = Design("D1", "bookish humor", 0.8, brief={"target_product": product_type})
    mockup_agent([design])
    assert design.product_type == product_type
    assert design.unit_cost == cost
    pricing_agent([design], target_margin=0.42, market_prices={product_type: 20})
    assert (design.price - cost) / design.price >= 0.42
    if product_type == "tote":
        assert design.price == 27.37
        assert PRODUCT_CATALOG_DETAILS["tote"] == {"name": TOTE_NAME, "size": "One size"}


@pytest.mark.parametrize(
    "product_type,product_id,variant_id,product_name",
    [("tote", 367, 10457, TOTE_NAME), ("mug", 19, 1320, "Mug"), ("tshirt", 71, 4012, "Tshirt")],
)
def test_staging_uses_catalog_for_listing_mockup_and_preview(
    tmp_path, monkeypatch, product_type, product_id, variant_id, product_name
):
    monkeypatch.setattr(pipeline, "DATA_DIR", tmp_path)
    images = tmp_path / "images"
    images.mkdir()
    artwork = images / "D1.png"
    artwork.write_bytes(b"artwork")
    design = Design(
        "D1", "bookish humor", 0.8, product_type=product_type,
        image_uri=str(artwork), prompt="Original artwork", price=27.37,
    )
    shop = {"shop_id": 1, "shipping_profile_id": 2, "readiness_state_id": 3, "return_policy_id": 4}
    etsy = Mock()
    etsy.create_draft_listing.return_value = {"listing_id": 5}
    etsy.upload_listing_image.return_value = {
        "url_fullxfull": "https://example.test/artwork.png", "listing_image_id": 6,
    }
    monkeypatch.setattr(pipeline, "etsy_client", etsy)
    printful = Mock()
    printful.is_configured.return_value = True
    printful.generate_mockup.return_value = "https://example.test/mockup.jpg"
    monkeypatch.setattr(pipeline, "printful_client", printful)
    download = Mock()
    download.content = b"mockup"
    monkeypatch.setattr(pipeline.requests, "get", Mock(return_value=download))

    entry = pipeline._stage_design(design, shop)

    listing = etsy.create_draft_listing.call_args.args[1]
    assert listing["title"] == f"Bookish Humor Design — {product_name}"
    if product_type == "tote":
        assert TOTE_NAME in listing["description"]
        assert "One size" in listing["description"]
        assert listing["taxonomy_id"] == 190
    else:
        assert listing["description"] == design.prompt
    printful.generate_mockup.assert_called_once_with(
        product_id, variant_id, "https://example.test/artwork.png"
    )
    printful.create_sync_product.assert_called_once_with(
        name=f"D1-{TOTE_NAME if product_type == 'tote' else product_type}",
        variant_id=variant_id, image_url="https://example.test/artwork.png",
        retail_price="27.37", preview_image_url="https://example.test/mockup.jpg",
    )
    assert etsy.upload_listing_image.call_count == 2
    etsy.reorder_listing_image.assert_called_once_with(1, 5, 6, rank=2)
    assert entry["mockup_image_url"] == "https://example.test/mockup.jpg"
    assert entry["status"] == "pending_approval"
    etsy.publish_listing.assert_not_called()
    printful.create_order_from_receipt.assert_not_called()


@pytest.mark.parametrize("placement", ["front", "default"])
def test_tote_mockup_uses_variant_print_area(monkeypatch, placement):
    get = Mock(side_effect=[
        {"result": {
            "printfiles": [{"printfile_id": 1, "width": 1500, "height": 1800}],
            "variant_printfiles": [{"variant_id": 10457, "placements": {placement: 1}}],
        }},
        {"result": {"status": "completed", "mockups": [{"mockup_url": "https://example.test/tote.jpg"}]}},
    ])
    post = Mock(return_value={"result": {"task_key": "test-task"}})
    monkeypatch.setattr(printful_client, "_get", get)
    monkeypatch.setattr(printful_client, "_post", post)
    assert printful_client.generate_mockup(367, 10457, "https://example.test/artwork.png") == (
        "https://example.test/tote.jpg"
    )
    assert get.call_args_list[0].args == ("/mockup-generator/printfiles/367",)
    path, body = post.call_args.args
    assert path == "/mockup-generator/create-task/367"
    assert body["variant_ids"] == [10457]
    assert body["files"] == [{
        "placement": placement, "image_url": "https://example.test/artwork.png",
        "position": {
            "area_width": 1500, "area_height": 1800, "width": 1500, "height": 1800,
            "top": 0, "left": 0,
        },
    }]


def test_mockup_preserves_requested_placement(monkeypatch):
    monkeypatch.setattr(printful_client, "get_variant_printfile", Mock(return_value={
        "front": {"width": 1500, "height": 1800},
        "back": {"width": 1200, "height": 1600},
    }))
    post = Mock(return_value={"result": {"task_key": "test-task"}})
    monkeypatch.setattr(printful_client, "_post", post)
    monkeypatch.setattr(printful_client, "_get", Mock(return_value={"result": {"status": "failed"}}))
    assert printful_client.generate_mockup(367, 10457, "https://example.test/artwork.png", placement="back") is None
    file = post.call_args.args[1]["files"][0]
    assert file["placement"] == "back"
    assert file["position"]["area_width"] == 1200


def test_mockup_failure_remains_best_effort(monkeypatch):
    monkeypatch.setattr(printful_client, "_get", Mock(side_effect=RuntimeError("unavailable")))
    post = Mock()
    monkeypatch.setattr(printful_client, "_post", post)
    assert printful_client.generate_mockup(367, 10457, "https://example.test/artwork.png") is None
    post.assert_not_called()


def test_tote_sync_product_keeps_artwork_and_preview_separate(monkeypatch):
    post = Mock(return_value={"result": {"id": 1}})
    monkeypatch.setattr(printful_client, "_post", post)
    result = printful_client.create_sync_product(
        name=f"D1-{TOTE_NAME}", variant_id=10457,
        image_url="https://example.test/artwork.png", retail_price="27.37",
        preview_image_url="https://example.test/tote.jpg",
    )
    assert result == {"id": 1}
    path, body = post.call_args.args
    assert path == "/store/products"
    assert body["sync_product"]["name"] == f"D1-{TOTE_NAME}"
    assert body["sync_variants"] == [{
        "retail_price": "27.37", "variant_id": 10457,
        "files": [
            {"type": "default", "url": "https://example.test/artwork.png"},
            {"type": "preview", "url": "https://example.test/tote.jpg"},
        ],
    }]


@pytest.mark.parametrize("with_marketing", [False, True])
def test_tote_listing_copy_uses_confirmed_name(with_marketing):
    design = Design(
        "D1", "bookish humor", 0.8, product_type="tote",
        compliance_status="pass", price=27.37,
    )
    if with_marketing:
        marketing_agent([design])
        assert design.marketing["primary_keyword"] == "bookish humor tote bag"
    client = Mock()
    client.create_listing.return_value = {"listing_id": 1, "state": "draft"}
    EtsyAdapter(client=client, draft_only=True).list_design(design, real=True)
    listing = client.create_listing.call_args.kwargs
    assert TOTE_NAME in listing["title"]
    assert TOTE_NAME in listing["description"]
    assert "One size" in listing["description"]
    assert listing["state"] == "draft"
    assert not design.approved
