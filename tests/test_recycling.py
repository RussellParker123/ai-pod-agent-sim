import json
from dataclasses import asdict

import pytest

from app.live import pipeline
from app.sim import recycling, run_simulation
from app.sim.agents import Design
from app.sim.manager import ManagerAgent


def _design(design_id="D1", niche="pet lovers", product="mug", image_uri="sim://images/D1.png",
            compliance="pass", notes=""):
    d = Design(design_id, niche, 0.8, prompt=f"Original vector illustration of a {niche} motif",
               image_uri=image_uri, compliance_status=compliance, compliance_notes=notes,
               product_type=product, unit_cost=5.0, price=15.0)
    return asdict(d)


def _store(tmp_path):
    return recycling.RecyclingStore(tmp_path / recycling.RECYCLING_FILENAME)


def test_enqueue_once_with_provenance_and_persisted(tmp_path):
    store = _store(tmp_path)
    rec, outcome = store.enqueue(_design(), rejected_by="manager", reason="score below hold",
                                 source="simulation", source_ref="run_1.json", stage="approval",
                                 provenance={"run": "run_1.json"})
    assert outcome == "created"
    dup, outcome2 = store.enqueue(_design(), rejected_by="manager", reason="again",
                                  source="simulation", source_ref="run_1.json")
    assert outcome2 == "duplicate" and dup["record_id"] == rec["record_id"]
    assert rec["image_uri"] == "sim://images/D1.png" and rec["source_design_id"] == "D1"
    assert rec["original"]["niche"] == "pet lovers" and rec["original"]["prompt"]
    assert rec["rejection"] == {"by": "manager", "reason": "score below hold", "stage": "approval"}
    assert rec["compliance"]["status"] == "pass" and rec["provenance"]["run"] == "run_1.json"
    store.save()
    reloaded = _store(tmp_path)
    assert len(reloaded.records) == 1 and reloaded.records[0]["record_id"] == rec["record_id"]


def test_concept_only_rejections_are_skipped_without_generation(tmp_path):
    store = _store(tmp_path)
    rec, outcome = store.enqueue(_design(image_uri=""), rejected_by="manager", reason="weak trend",
                                 source="simulation")
    assert rec is None and outcome == "skipped_no_image" and store.records == []


def test_cross_reference_suggestions_are_explainable_and_reference_backed(tmp_path):
    store = _store(tmp_path)
    design = _design(niche="bookish humor", product="tshirt", image_uri=str(tmp_path / "x.png"))
    rec, _ = store.enqueue(design, rejected_by="manager", reason="poor product fit", source="live")
    context = recycling.build_context(
        research={"top_product_types": ["tote"], "top_niches": {"bookish humor": 0.9}},
        approved_designs=[{"design_id": "A7", "niche": "bookish humor", "product_type": "tote"}],
    )
    store.analyze(rec["record_id"], context)
    analysis = rec["analysis"]
    assert rec["status"] == recycling.PENDING_REVIEW
    assert analysis["method"] == "metadata_cross_reference" and analysis["image_inspected"] is False
    assert "pixels were not inspected" in analysis["limitations"]
    top = analysis["suggestions"][0]
    assert top["type"] == "alternate_product" and top["target_product"] == "tote"
    assert "approved_design:A7" in top["references"] and "research:top_product_types:tote" in top["references"]
    assert top["reasons"] and 0 < top["confidence"] <= 0.95


def test_compliance_flagged_assets_are_quarantined_and_blocked(tmp_path):
    store = _store(tmp_path)
    rec, _ = store.enqueue(_design(compliance="flagged", notes="possible trademark similarity"),
                           rejected_by="compliance", reason="flagged", source="simulation")
    store.analyze(rec["record_id"], recycling.build_context())
    assert rec["status"] == recycling.QUARANTINED
    assert [s["type"] for s in rec["analysis"]["suggestions"]] == ["quarantine"]
    with pytest.raises(recycling.RecyclingError, match="Quarantined"):
        store.review(rec["record_id"], "request_reuse", suggestion_id=rec["analysis"]["suggestions"][0]["suggestion_id"])
    assert store.is_blocked_image(rec["image_uri"])


def _ready_record(store):
    rec, _ = store.enqueue(_design(niche="pet lovers", product="tote"), rejected_by="human",
                           reason="canceled", source="simulation", source_ref="run_1.json")
    store.analyze(rec["record_id"], recycling.build_context())
    reusable = [s for s in rec["analysis"]["suggestions"] if s["type"] in recycling.REUSABLE_TYPES]
    return rec, reusable[0]


def test_reuse_is_idempotent_keeps_image_and_requires_fresh_gates(tmp_path):
    store = _store(tmp_path)
    rec, suggestion = _ready_record(store)
    store.review(rec["record_id"], "request_reuse", suggestion_id=suggestion["suggestion_id"])
    again = store.review(rec["record_id"], "request_reuse", suggestion_id=suggestion["suggestion_id"])
    assert again["status"] == recycling.REUSE_REQUESTED
    assert sum(h["action"] == "request_reuse" for h in rec["history"]) == 1

    candidate = store.build_candidate(rec["record_id"])
    assert candidate.image_uri == rec["image_uri"]
    assert candidate.approved is False and candidate.compliance_status == "pending"
    assert candidate.lineage["recycled_from"] == rec["record_id"]
    assert candidate.lineage["original_rejection"]["reason"] == "canceled"
    assert candidate.product_type == suggestion["target_product"]
    assert rec["rejection"]["reason"] == "canceled"  # original record never flipped to approved

    store.mark_reentered(rec["record_id"], "run_2.json", {"compliance": "pass"})
    store.mark_reentered(rec["record_id"], "run_2.json", {"compliance": "pass"})
    assert sum(h["action"] == "reentered_pipeline" for h in rec["history"]) == 1
    with pytest.raises(recycling.RecyclingError):
        store.review(rec["record_id"], "archive")


def test_archive_and_unusable_are_idempotent(tmp_path):
    store = _store(tmp_path)
    rec, _ = _ready_record(store)
    store.review(rec["record_id"], "archive")
    store.review(rec["record_id"], "archive")
    assert sum(h["action"] == "archive" for h in rec["history"]) == 1
    with pytest.raises(recycling.RecyclingError, match="Cannot request reuse"):
        store.review(rec["record_id"], "request_reuse", suggestion_id="whatever")
    with pytest.raises(recycling.RecyclingError, match="Unknown action"):
        store.review(rec["record_id"], "publish")


def test_analysis_attempts_and_reuse_depth_are_capped(tmp_path):
    store = _store(tmp_path)
    rec, _ = store.enqueue(_design(), rejected_by="manager", reason="x", source="simulation")
    for _ in range(recycling.MAX_ANALYSIS_ATTEMPTS):
        store.analyze(rec["record_id"], recycling.build_context())
    with pytest.raises(recycling.RecyclingError, match="analysis limit"):
        store.analyze(rec["record_id"], recycling.build_context())

    recycled_again = _design("D1-R1-abcd")
    recycled_again["lineage"] = {"recycled_from": rec["record_id"], "depth": 1}
    loop, _ = store.enqueue(recycled_again, rejected_by="manager", reason="still bad", source="simulation")
    assert loop["status"] == recycling.UNUSABLE


def test_safe_image_path_blocks_traversal(tmp_path):
    images = tmp_path / "images"
    images.mkdir()
    (images / "ok.png").write_bytes(b"x")
    (tmp_path / "secret.png").write_bytes(b"x")
    assert recycling.safe_image_path(str(images / "ok.png"), images) == (images / "ok.png").resolve()
    assert recycling.safe_image_path("../secret.png", images) is None
    assert recycling.safe_image_path(str(tmp_path / "secret.png"), images) is None
    assert recycling.safe_image_path("https://example.com/a.png", images) is None
    assert recycling.safe_image_path(str(images / "ok.txt"), images) is None


def test_human_cancel_on_review_page_queues_once(tmp_path):
    store = _store(tmp_path)
    designs = [_design("D1"), _design("D2", image_uri="")]
    first = recycling.enqueue_human_rejections(store, "run_1.json", designs, ["D1", "D2", "D9"],
                                               recycling.build_context())
    second = recycling.enqueue_human_rejections(store, "run_1.json", designs, ["D1"], recycling.build_context())
    assert len(first["created"]) == 1 and first["skipped_no_image"] == ["D2"] and first["unknown"] == ["D9"]
    assert second["duplicate"] == first["created"] and len(store.records) == 1
    assert store.records[0]["rejection"]["by"] == "human"


def _isolate_sim(tmp_path, monkeypatch):
    monkeypatch.setattr(run_simulation, "DATA_DIR", tmp_path)
    monkeypatch.setattr(run_simulation.EtsyConnector, "from_environment", lambda: None)
    captured = []
    monkeypatch.setattr(run_simulation, "save_json", lambda payload, name: captured.append(payload) or name)
    return captured


def test_simulation_blocks_feed_recycling_and_reuse_reenters_gates(tmp_path, monkeypatch):
    captured = _isolate_sim(tmp_path, monkeypatch)
    original = ManagerAgent.score_and_decide

    def block_first_two(self, designs):
        original(self, designs)
        for d in designs[:2]:
            self.design_scores[d.design_id].update(manager_decision="BLOCK", reasons=["test block"])
            d.approved = False

    monkeypatch.setattr(ManagerAgent, "score_and_decide", block_first_two)
    run_simulation.run_once()
    summary = captured[0]["recycling"]
    assert len(summary["enqueued"]) >= 2
    store = _store(tmp_path)
    assert {r["source"] for r in store.records} == {"simulation"}
    assert all(r["analysis"] for r in store.records)  # recycler department analysed them

    rec = next(r for r in store.records if r["status"] == recycling.PENDING_REVIEW
               and any(s["type"] in recycling.REUSABLE_TYPES for s in r["analysis"]["suggestions"]))
    sid = next(s["suggestion_id"] for s in rec["analysis"]["suggestions"] if s["type"] in recycling.REUSABLE_TYPES)
    store.review(rec["record_id"], "request_reuse", suggestion_id=sid)
    store.save()

    monkeypatch.setattr(ManagerAgent, "score_and_decide", original)
    run_simulation.run_once()
    payload = captured[1]
    reused = [d for d in payload["designs"] if d["lineage"].get("recycled_from") == rec["record_id"]]
    assert len(reused) == 1 and reused[0]["image_uri"] == rec["image_uri"]
    assert reused[0]["design_id"] in payload["manager"]["design_scores"]  # went through manager gate
    assert payload["recycling"]["reentered"] == [reused[0]["design_id"]]
    after = _store(tmp_path).get(rec["record_id"])
    assert after["status"] == recycling.REENTERED and after["reuse"]["gates"]["human_approval"].startswith("pending")
    # rerunning does not re-add the same candidate
    run_simulation.run_once()
    assert not any(d["lineage"].get("recycled_from") == rec["record_id"] for d in captured[2]["designs"])


def test_recycled_candidates_never_auto_list(tmp_path, monkeypatch):
    captured = _isolate_sim(tmp_path, monkeypatch)
    store = _store(tmp_path)
    rec, suggestion = _ready_record(store)
    store.review(rec["record_id"], "request_reuse", suggestion_id=suggestion["suggestion_id"])
    store.save()
    listed = []

    class Adapter:
        def list_design(self, design, real=False):
            listed.append(design.design_id)
            return {"mode": "draft", "listing_id": "x", "status": "draft"}

    monkeypatch.setattr("app.marketplace.adapter.get_adapter", lambda *a, **k: Adapter())
    original = ManagerAgent.score_and_decide

    def greenlight_all(self, designs):
        original(self, designs)
        for d in designs:
            if d.compliance_status == "pass":
                d.approved = True

    monkeypatch.setattr(ManagerAgent, "score_and_decide", greenlight_all)
    run_simulation.run_once(draft_only=True)
    candidate_id = store.get(rec["record_id"])["reuse"]["candidate_design_id"]
    assert candidate_id in {d["design_id"] for d in captured[0]["designs"]}
    assert candidate_id not in listed and listed


@pytest.fixture
def live_env(tmp_path, monkeypatch):
    images = tmp_path / "images"
    images.mkdir()
    monkeypatch.setattr(pipeline, "DATA_DIR", tmp_path)
    monkeypatch.setattr(pipeline, "IMAGES_DIR", images)
    monkeypatch.setattr(pipeline, "PENDING_APPROVALS_PATH", tmp_path / "pending_approvals.json")
    monkeypatch.setattr(pipeline, "IMAGE_MANIFEST_PATH", tmp_path / "image_manifest.json")
    monkeypatch.setattr(pipeline, "RECYCLING_PATH", tmp_path / recycling.RECYCLING_FILENAME)

    def forbidden(*args, **kwargs):
        raise AssertionError("no publishing / paid image generation allowed")

    monkeypatch.setattr(pipeline.etsy_client, "publish_listing", forbidden)
    monkeypatch.setattr(pipeline.openai_image, "image_agent_live_stream", forbidden)
    return tmp_path, images


def test_live_reject_queues_image_once_without_deleting(live_env):
    tmp_path, images = live_env
    img = images / "L5.png"
    img.write_bytes(b"\x89PNG fake")
    entry = dict(_design("L5", image_uri=str(img)), status="pending_approval", etsy_listing_id=42)
    (tmp_path / "pending_approvals.json").write_text(json.dumps([entry]))
    rejected = pipeline.reject("L5", reason="colors clash on the mug")
    assert rejected["status"] == "rejected" and img.exists()
    store = _store(tmp_path)
    assert len(store.records) == 1
    rec = store.records[0]
    assert rec["source"] == "live" and rec["rejection"] == {"by": "human", "reason": "colors clash on the mug",
                                                            "stage": "human_review"}
    assert rec["provenance"]["etsy_listing_id"] == 42 and rec["analysis"] is not None
    with pytest.raises(ValueError):
        pipeline.reject("L5")  # already rejected: no second record
    assert len(_store(tmp_path).records) == 1


def test_orphan_archive_image_goes_to_manual_review(live_env):
    tmp_path, images = live_env
    (images / "orphan.png").write_bytes(b"\x89PNG fake")
    rec = pipeline.hold_archive_image_for_reuse("orphan")
    assert rec["provenance"]["orphan"] is True and rec["status"] == recycling.QUARANTINED
    assert pipeline.hold_archive_image_for_reuse("orphan")["record_id"] == rec["record_id"]
    with pytest.raises(ValueError, match="quarantined"):
        pipeline.stage_archived_image("orphan", str(images / "orphan.png"), "pets", "mug", 15.0, "desc")


def test_stage_recycled_candidate_runs_gates_and_never_publishes(live_env, monkeypatch):
    tmp_path, images = live_env
    img = images / "L7.png"
    img.write_bytes(b"\x89PNG fake")
    store = pipeline._recycling_store()
    rec, _ = store.enqueue(_design("L7", niche="pet lovers", product="tote", image_uri=str(img)),
                           rejected_by="human", reason="wrong product", source="live", source_ref="live")
    store.analyze(rec["record_id"], recycling.build_context(), images_root=images)
    sid = next(s["suggestion_id"] for s in rec["analysis"]["suggestions"] if s["type"] in recycling.REUSABLE_TYPES)
    store.review(rec["record_id"], "request_reuse", suggestion_id=sid)
    store.save()

    staged = []
    monkeypatch.setattr(pipeline, "load_etsy_config", lambda: {"target_margin": 0.42})
    monkeypatch.setattr(pipeline, "compliance_agent", lambda ds: [setattr(d, "compliance_status", "pass") for d in ds])
    monkeypatch.setattr(pipeline, "_get_shop_context", lambda: {"shop_id": 1})

    def fake_stage(design, shop):
        staged.append(design)
        return {"design_id": design.design_id, "image_uri": design.image_uri, "status": "pending_approval",
                "published_by": "nobody-should-set-this"}

    monkeypatch.setattr(pipeline, "_stage_design", fake_stage)
    result = pipeline.stage_recycled_candidate(rec["record_id"])
    assert result["status"] == "staged" and staged[0].image_uri == str(img)
    entry = result["entry"]
    assert entry["published_by"] is None and entry["source"] == "recycling" and entry["status"] == "pending_approval"
    assert set(result["gates"]) == {"compliance", "quality", "pricing", "manager"}
    after = pipeline._recycling_store().get(rec["record_id"])
    assert after["status"] == recycling.REENTERED
    assert after["reuse"]["gates"]["human_approval"].startswith("pending")
    assert pipeline.stage_recycled_candidate(rec["record_id"])["status"] == "already_reentered"
    assert len(staged) == 1


def test_stage_recycled_candidate_blocked_by_fresh_compliance(live_env, monkeypatch):
    tmp_path, images = live_env
    img = images / "L8.png"
    img.write_bytes(b"\x89PNG fake")
    store = pipeline._recycling_store()
    rec, _ = store.enqueue(_design("L8", niche="pet lovers", product="tote", image_uri=str(img)),
                           rejected_by="human", reason="meh", source="live", source_ref="live")
    store.analyze(rec["record_id"], recycling.build_context(), images_root=images)
    sid = next(s["suggestion_id"] for s in rec["analysis"]["suggestions"] if s["type"] in recycling.REUSABLE_TYPES)
    store.review(rec["record_id"], "request_reuse", suggestion_id=sid)
    store.save()
    monkeypatch.setattr(pipeline, "load_etsy_config", lambda: {})
    monkeypatch.setattr(pipeline, "compliance_agent",
                        lambda ds: [setattr(d, "compliance_status", "flagged") for d in ds])
    monkeypatch.setattr(pipeline, "_stage_design", lambda *a: pytest.fail("must not reach Etsy"))
    result = pipeline.stage_recycled_candidate(rec["record_id"])
    assert result["status"] == "blocked" and result["gates"]["manager"] == "BLOCK"
    assert pipeline._load_pending() == []


def test_outcome_counts_groups():
    records = [{"status": s} for s in recycling.STATUSES]
    assert recycling.outcome_counts(records) == {"pending_reuse": 4, "quarantined": 1, "unusable": 2}


def test_quarantine_is_sticky_and_cannot_be_archived_into_sellable(tmp_path):
    store = recycling.RecyclingStore(tmp_path / "q.json")
    design = {"design_id": "F1", "niche": "cozy cats", "product": "mug", "prompt": "p",
              "image_uri": "sim://F1", "compliance_status": "flagged"}
    rec, _ = store.enqueue(design, rejected_by="manager", reason="flagged", source="simulation", source_ref="r")
    store.analyze(rec["record_id"], context={})
    assert store.get(rec["record_id"])["status"] == recycling.QUARANTINED
    try:
        store.review(rec["record_id"], "archive")
        assert False, "archiving a quarantined asset must be refused"
    except recycling.RecyclingError:
        pass
    store.review(rec["record_id"], "mark_unusable")
    assert store.is_blocked_image("sim://F1")
    # even if a record's status were changed by hand, the recorded quarantine still blocks it
    store.get(rec["record_id"])["status"] = recycling.ARCHIVED
    assert store.is_blocked_image("sim://F1")
