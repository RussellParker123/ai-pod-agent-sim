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


def _printfiles(placements, fill_mode, width=1800, height=2400):
    return {"result": {
        "printfiles": [{"printfile_id": 1, "width": width, "height": height, "fill_mode": fill_mode}],
        "variant_printfiles": [{"variant_id": 4012, "placements": {p: 1 for p in placements}}],
    }}


def test_tshirt_mockup_uses_front_and_fits_square_art(monkeypatch):
    get = Mock(side_effect=[
        _printfiles(["label_outside", "back", "front"], "fit"),
        {"result": {"status": "completed", "mockups": [
            {"placement": "back", "mockup_url": "https://example.test/back.jpg"},
            {"placement": "front", "mockup_url": "https://example.test/front.jpg"},
        ]}},
    ])
    post = Mock(return_value={"result": {"task_key": "test-task"}})
    monkeypatch.setattr(printful_client, "_get", get)
    monkeypatch.setattr(printful_client, "_post", post)
    assert printful_client.generate_mockup(71, 4012, "https://example.test/art.png") == "https://example.test/front.jpg"
    file = post.call_args.args[1]["files"][0]
    assert file["placement"] == "front"
    assert file["position"] == {
        "area_width": 1800, "area_height": 2400, "width": 1800, "height": 1800, "top": 300, "left": 0,
    }


def test_cover_print_area_is_still_filled_edge_to_edge(monkeypatch):
    get = Mock(side_effect=[
        _printfiles(["default"], "cover", width=2700, height=1050),
        {"result": {"status": "completed", "mockups": [{"mockup_url": "https://example.test/mug.jpg"}]}},
    ])
    post = Mock(return_value={"result": {"task_key": "test-task"}})
    monkeypatch.setattr(printful_client, "_get", get)
    monkeypatch.setattr(printful_client, "_post", post)
    assert printful_client.generate_mockup(19, 4012, "https://example.test/art.png") == "https://example.test/mug.jpg"
    assert post.call_args.args[1]["files"][0]["position"] == {
        "area_width": 2700, "area_height": 1050, "width": 2700, "height": 1050, "top": 0, "left": 0,
    }


def test_mockup_retries_rate_limit_and_waits_for_slow_tasks(monkeypatch):
    import requests

    limited = requests.HTTPError(response=Mock(status_code=429, headers={"Retry-After": "5"}))
    post = Mock(side_effect=[limited, {"result": {"task_key": "test-task"}}])
    get = Mock(side_effect=[
        _printfiles(["front"], "fit"),
        *[{"result": {"status": "pending"}}] * 20,
        {"result": {"status": "completed", "mockups": [{"mockup_url": "https://example.test/tote.jpg"}]}},
    ])
    clock = {"now": 0.0}
    monkeypatch.setattr(printful_client.time, "time", lambda: clock["now"])
    monkeypatch.setattr(printful_client.time, "sleep", lambda s: clock.__setitem__("now", clock["now"] + s))
    monkeypatch.setattr(printful_client, "_get", get)
    monkeypatch.setattr(printful_client, "_post", post)
    assert printful_client.generate_mockup(367, 10457, "https://example.test/art.png") == "https://example.test/tote.jpg"
    assert post.call_count == 2
    assert clock["now"] > 45  # longer than the old 45s cap that dropped apparel/tote mockups


def test_mockup_non_rate_limit_error_is_not_retried(monkeypatch):
    import requests

    post = Mock(side_effect=requests.HTTPError(response=Mock(status_code=400, headers={})))
    monkeypatch.setattr(printful_client, "_get", Mock(return_value=_printfiles(["front"], "fit")))
    monkeypatch.setattr(printful_client, "_post", post)
    assert printful_client.generate_mockup(71, 4012, "https://example.test/art.png") is None
    assert post.call_count == 1


def _stage(tmp_path, monkeypatch, mockup_url):
    monkeypatch.setattr(pipeline, "DATA_DIR", tmp_path)
    monkeypatch.setattr(pipeline, "PENDING_APPROVALS_PATH", tmp_path / "pending.json")
    artwork = tmp_path / "D1.png"
    artwork.write_bytes(b"artwork")
    design = Design("D1", "bookish humor", 0.8, product_type="tshirt", image_uri=str(artwork),
                    prompt="Original artwork", price=27.37)
    etsy = Mock()
    etsy.create_draft_listing.return_value = {"listing_id": 5}
    etsy.upload_listing_image.return_value = {"url_fullxfull": "https://example.test/artwork.png", "listing_image_id": 6}
    printful = Mock()
    printful.is_configured.return_value = True
    printful.generate_mockup.return_value = mockup_url
    printful.create_sync_product.return_value = {"id": 77}
    monkeypatch.setattr(pipeline, "etsy_client", etsy)
    monkeypatch.setattr(pipeline, "printful_client", printful)
    download = Mock(content=b"mockup")
    monkeypatch.setattr(pipeline.requests, "get", Mock(return_value=download))
    shop = {"shop_id": 1, "shipping_profile_id": 2, "readiness_state_id": 3, "return_policy_id": 4}
    return pipeline._stage_design(design, shop), etsy, printful


def test_staging_falls_back_to_flat_art_when_mockup_fails(tmp_path, monkeypatch):
    entry, etsy, printful = _stage(tmp_path, monkeypatch, None)
    assert entry["mockup_image_url"] is None and entry["mockup_image_uri"] is None
    assert entry["etsy_image_url"] == "https://example.test/artwork.png"
    assert etsy.upload_listing_image.call_count == 1
    etsy.reorder_listing_image.assert_not_called()
    assert printful.create_sync_product.call_args.kwargs["preview_image_url"] is None


def test_staging_records_local_mockup_even_without_images_dir(tmp_path, monkeypatch):
    entry, _, _ = _stage(tmp_path, monkeypatch, "https://example.test/mockup.jpg")
    assert entry["mockup_image_uri"] == str(tmp_path / "images" / "D1_mockup.jpg")
    assert (tmp_path / "images" / "D1_mockup.jpg").read_bytes() == b"mockup"
    assert entry["etsy_flat_image_id"] == 6


def test_refresh_mockups_backfills_existing_flat_only_listings(tmp_path, monkeypatch):
    entry, etsy, printful = _stage(tmp_path, monkeypatch, None)
    del entry["etsy_flat_image_id"]  # entries staged before this field existed
    done = dict(entry, design_id="D2", mockup_image_url="https://example.test/old.jpg")
    pipeline._save_pending([entry, done])
    etsy.reset_mock()
    etsy.get_listing_images.return_value = [
        {"listing_image_id": 6, "rank": 1, "url_fullxfull": "https://example.test/artwork.png"},
    ]
    printful.generate_mockup.reset_mock()
    printful.generate_mockup.return_value = "https://example.test/mockup.jpg"

    refreshed = pipeline.refresh_mockups()

    assert [e["design_id"] for e in refreshed] == ["D1"]
    printful.generate_mockup.assert_called_once_with(71, 4012, "https://example.test/artwork.png")
    etsy.upload_listing_image.assert_called_once_with(1, 5, str(tmp_path / "images" / "D1_mockup.jpg"))
    etsy.reorder_listing_image.assert_called_once_with(1, 5, 6, rank=2)
    printful.set_sync_product_preview.assert_called_once_with(
        77, "https://example.test/artwork.png", "https://example.test/mockup.jpg"
    )
    saved = {e["design_id"]: e for e in pipeline.list_all()}
    assert saved["D1"]["mockup_image_url"] == "https://example.test/mockup.jpg"
    assert saved["D2"]["mockup_image_url"] == "https://example.test/old.jpg"


def test_set_sync_product_preview_updates_every_sync_variant(monkeypatch):
    monkeypatch.setattr(printful_client, "_get", Mock(return_value={"result": {"sync_variants": [{"id": 9}]}}))
    put = Mock(return_value={"result": {"id": 9}})
    monkeypatch.setattr(printful_client, "_put", put)
    assert printful_client.set_sync_product_preview(77, "https://a/art.png", "https://a/mock.jpg") == [{"id": 9}]
    put.assert_called_once_with("/store/variants/9", {"files": [
        {"type": "default", "url": "https://a/art.png"}, {"type": "preview", "url": "https://a/mock.jpg"},
    ]})


def test_reorder_failure_keeps_uploaded_mockup(tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline, "DATA_DIR", tmp_path)
    etsy = Mock()
    etsy.reorder_listing_image.side_effect = RuntimeError("etsy hiccup")
    printful = Mock()
    printful.is_configured.return_value = True
    printful.generate_mockup.return_value = "https://example.test/mockup.jpg"
    monkeypatch.setattr(pipeline, "etsy_client", etsy)
    monkeypatch.setattr(pipeline, "printful_client", printful)
    monkeypatch.setattr(pipeline.requests, "get", Mock(return_value=Mock(content=b"mockup")))
    url, path = pipeline._attach_mockup("D1", "tote", 1, 5, "https://example.test/artwork.png", 6)
    assert url == "https://example.test/mockup.jpg"
    assert path == str(tmp_path / "images" / "D1_mockup.jpg")
    etsy.upload_listing_image.assert_called_once()
