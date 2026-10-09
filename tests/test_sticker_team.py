import json
from dataclasses import asdict

import pytest

from app.live import pipeline
from app.sim import recycling, sticker_team
from app.sim.agents import Design


@pytest.fixture
def sticker_live_env(tmp_path, monkeypatch):
    images = tmp_path / "images"
    images.mkdir()
    monkeypatch.setattr(pipeline, "DATA_DIR", tmp_path)
    monkeypatch.setattr(pipeline, "IMAGES_DIR", images)
    monkeypatch.setattr(pipeline, "PENDING_APPROVALS_PATH", tmp_path / "pending_approvals.json")
    monkeypatch.setattr(pipeline, "IMAGE_MANIFEST_PATH", tmp_path / "image_manifest.json")
    monkeypatch.setattr(pipeline, "RECYCLING_PATH", tmp_path / recycling.RECYCLING_FILENAME)
    return tmp_path, images


def _live_record(store, image, compliance="pass"):
    image.write_bytes(b"\x89PNG fake")
    design = asdict(Design(
        "L-STICKER", "pet lovers", 0.8,
        prompt="Original pet illustration in a bold vector style",
        image_uri=str(image), compliance_status=compliance, product_type="tote",
    ))
    record, _ = store.enqueue(design, "human", "rejected", "live", source_ref="live")
    store.analyze(record["record_id"], recycling.build_context(), images_root=image.parent)
    return record


def _approve_sticker(store, record, images):
    sticker_team.submit_team_review(store, record["record_id"], images)
    sticker_team.overseer_review(store, record["record_id"], images)
    sticker_team.cypher_approve(store, record["record_id"], images)


def test_sticker_approval_chain_is_sequential_and_audited(tmp_path):
    images = tmp_path / "images"
    images.mkdir()
    store = recycling.RecyclingStore(tmp_path / recycling.RECYCLING_FILENAME)
    record = _live_record(store, images / "photo.png")

    with pytest.raises(recycling.RecyclingError, match="team must review"):
        sticker_team.overseer_review(store, record["record_id"], images)
    sticker_team.submit_team_review(store, record["record_id"], images)
    sticker_team.overseer_review(store, record["record_id"], images)
    assert record["sticker_workflow"]["status"] == "awaiting_cypher"
    assert record["sticker_workflow"]["overseer"]["approved"] is True
    sticker_team.cypher_approve(store, record["record_id"], images)
    assert record["sticker_workflow"]["status"] == "approved"
    assert [event["action"] for event in record["history"][-3:]] == [
        "sticker_team_reviewed", "sticker_overseer_reviewed", "sticker_cypher_approved",
    ]


def test_sticker_workflow_refuses_quarantined_or_missing_images(tmp_path):
    images = tmp_path / "images"
    images.mkdir()
    store = recycling.RecyclingStore(tmp_path / recycling.RECYCLING_FILENAME)
    record = _live_record(store, images / "flagged.png", compliance="flagged")

    with pytest.raises(recycling.RecyclingError, match="Quarantined"):
        sticker_team.submit_team_review(store, record["record_id"], images)

    safe_record = _live_record(store, images / "safe.png")
    (images / "safe.png").unlink()
    with pytest.raises(recycling.RecyclingError, match="missing"):
        sticker_team.submit_team_review(store, safe_record["record_id"], images)


def test_recycled_sticker_stages_once_after_agent_approvals(sticker_live_env, monkeypatch):
    tmp_path, images = sticker_live_env
    store = pipeline._recycling_store()
    record = _live_record(store, images / "L9.png")
    _approve_sticker(store, record, images)
    store.save()

    monkeypatch.setattr(pipeline, "sticker_configuration_errors", lambda: [])
    monkeypatch.setattr(pipeline.printful_client, "is_configured", lambda: True)
    monkeypatch.setattr(pipeline, "PRODUCT_UNIT_COSTS", {"sticker": 2.0})
    monkeypatch.setattr(pipeline, "load_etsy_config", lambda: {"target_margin": 0.42})
    monkeypatch.setattr(pipeline, "compliance_agent",
                        lambda designs: [setattr(d, "compliance_status", "pass") for d in designs])
    monkeypatch.setattr(pipeline, "assess_concept", lambda design: {"status": "pass", "issues": []})
    monkeypatch.setattr(pipeline, "_get_shop_context", lambda: {"shop_id": 1})
    staged = []

    def fake_stage(design, shop):
        staged.append(design)
        return {"design_id": design.design_id, "product_type": design.product_type,
                "image_uri": design.image_uri, "status": "pending_approval"}

    monkeypatch.setattr(pipeline, "_stage_design", fake_stage)
    persisted = pipeline._recycling_store()
    stored_record = persisted.get(record["record_id"])
    stored_record["sticker_workflow"]["dr_cypher"]["agent_id"] = "other-agent"
    persisted.save()
    with pytest.raises(recycling.RecyclingError, match="complete"):
        pipeline.stage_recycled_sticker(record["record_id"])
    persisted = pipeline._recycling_store()
    persisted.get(record["record_id"])["sticker_workflow"]["dr_cypher"]["agent_id"] = sticker_team.CYPHER_ID
    persisted.save()
    result = pipeline.stage_recycled_sticker(record["record_id"])
    assert result["status"] == "staged"
    assert result["entry"]["product_type"] == "sticker"
    assert result["entry"]["image_uri"] == str(images / "L9.png")
    assert result["entry"]["status"] == "pending_approval"
    assert result["entry"]["published_by"] is None
    assert pipeline.stage_recycled_sticker(record["record_id"])["status"] == "already_staged"
    assert len(staged) == 1
    assert json.loads((tmp_path / "pending_approvals.json").read_text())[0]["source"] == "recycling_sticker"
