import struct
import zlib

from app.live import pipeline
from app.sim.agents import Design, prompt_agent
from app.sim.art_quality import (
    MAX_COMPLIANCE_REWORKS,
    assess_concept,
    assess_generated_image,
    build_brief,
    refine_designs,
    render_prompt,
    revise_for_compliance,
)
from app.sim.manager import ManagerAgent

RESEARCH = {"source": "simulated", "top_niches": {"coffee culture": 1.0}, "top_styles": ["retro"],
            "top_product_types": ["mug"]}


def _design(design_id="D1", niche="coffee culture", prompt=""):
    return Design(design_id, niche, 0.9, prompt=prompt)


def test_brief_is_structured_product_aware_and_research_fed():
    d = _design()
    prompt_agent([d], research=RESEARCH, product_types=("mug", "tshirt", "tote"))
    brief = d.brief
    for key in ("niche", "concept", "motif", "target_product", "composition", "style", "palette",
                "legibility", "print_constraints", "originality", "reviewer_feedback"):
        assert key in brief
    assert brief["target_product"] == "mug"  # best product-fit for coffee culture
    assert brief["research_signals"]["top_styles"] == ["retro"]
    assert "Print:" in d.prompt and "no logos" in d.prompt.lower()
    check = assess_concept(d)
    assert check["status"] == "pass" and check["image_inspected"] is False
    assert {c["name"] for c in check["checks"]} >= {"protected_terms", "product_fit", "legibility",
                                                     "print_constraints", "originality_guardrails"}


def test_refinement_is_bounded_and_records_feedback():
    d = _design(prompt='Disney style mug with "good morning to every single sleepy coffee lover"')
    d.brief = build_brief(d, product_types=("mug",))
    d.prompt = d.prompt  # an incoming prompt that ignores the brief
    summary = refine_designs([d], product_types=("mug",), max_rounds=2)
    assert summary["revised"] <= 2
    assert d.quality["concept"]["status"] == "pass"
    assert "disney" not in d.prompt.lower()
    revision = [h for h in d.review_history if h["type"] == "revision"]
    assert revision and revision[0]["feedback"]  # auditable, concrete feedback
    assert d.brief["revision"] >= 1


def test_refinement_round_budget_is_respected():
    d = _design(prompt="coffee")  # generic prompt without guardrails or print spec
    d.brief = build_brief(d, product_types=("mug",))
    summary = refine_designs([d], product_types=("mug",), max_rounds=0)
    assert summary == {"checked": 1, "revised": 0, "passed": 0, "blocked": 0, "needs_revision": 1}
    assert d.prompt == "coffee" and d.review_history == []
    assert d.quality["concept"]["feedback"]  # explains what to fix


def test_niche_level_protected_name_is_a_blocker_not_fixable():
    d = _design(niche="marvel heroes")
    prompt_agent([d], product_types=("tshirt",))
    refine_designs([d], product_types=("tshirt",))
    assert d.quality["concept"]["status"] == "blocked"
    manager = ManagerAgent()
    d.compliance_status, d.product_type, d.unit_cost, d.price = "pass", "tshirt", 10, 30
    manager.score_and_decide([d])
    assert manager.score_for(d)["manager_decision"] == "BLOCK"
    assert any("concept pre-check blocker" in r for r in manager.score_for(d)["reasons"])


def test_unchanged_flagged_design_is_not_rechecked_and_rework_is_capped():
    manager = ManagerAgent()
    d = _design()
    prompt_agent([d], product_types=("mug",))
    d.compliance_status, d.compliance_notes = "flagged", "possible trademark similarity"
    rechecked = []
    # revise() that never changes anything: no re-roll, design is rejected
    manager.review_compliance([d], recheck=lambda items: rechecked.extend(items), revise=lambda _d: False)
    assert rechecked == [] and d.compliance_status == "flagged"
    assert manager.decisions[-1].action == "reject"

    # real rework: re-checked once, then the cap stops further reworks
    assert revise_for_compliance(d, product_types=("mug",)) is True
    assert d.brief["compliance_reworks"] == MAX_COMPLIANCE_REWORKS
    assert any(h["source"] == "compliance" for h in d.review_history)
    assert revise_for_compliance(d, product_types=("mug",)) is False


def test_compliance_blockers_still_block_after_rework():
    manager = ManagerAgent()
    d = _design()
    prompt_agent([d], product_types=("mug",))
    d.compliance_status, d.compliance_notes = "flagged", "possible trademark similarity"

    def still_flagged(items):
        for item in items:
            item.compliance_status = "flagged"

    manager.review_compliance([d], recheck=still_flagged,
                              revise=lambda x: revise_for_compliance(x, product_types=("mug",)))
    d.product_type, d.unit_cost, d.price = "mug", 5, 20
    manager.score_and_decide([d])
    assert manager.score_for(d)["manager_decision"] == "BLOCK" and d.approved is False


def _png(path, w, h):
    raw = b"".join(b"\x00" + b"\x00\x00\x00" * w for _ in range(h))

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
                     + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def test_image_assessment_is_separate_and_falls_back_offline(tmp_path):
    d = _design()
    assert assess_generated_image(d)["status"] == "no_image"
    d.image_uri = "sim://images/D1.png"
    assert assess_generated_image(d)["status"] == "simulated"
    d.image_uri = str(tmp_path / "missing.png")
    assert assess_generated_image(d)["status"] == "missing_file"

    img = tmp_path / "D1.png"
    _png(img, 4, 4)
    d.image_uri = str(img)
    offline = assess_generated_image(d)
    assert offline["status"] == "not_assessed" and offline["image_inspected"] is False
    assert offline["file_checks"]["width"] == 4 and offline["file_checks"]["min_side_ok"] is False

    def broken(path, brief):
        raise RuntimeError("vision API unavailable")

    fallback = assess_generated_image(d, assessor=broken)
    assert fallback["status"] == "assessor_unavailable" and fallback["image_inspected"] is False
    assessed = assess_generated_image(d, assessor=lambda path, brief: {"ok": True})
    assert assessed["status"] == "assessed" and assessed["image_inspected"] is True
    assert d.image_uri == str(img)  # never regenerated


def test_variants_have_independent_metadata_and_inherit_parent_score():
    d = _design("D010")
    prompt_agent([d], product_types=("mug",))
    d.review_history.append({"type": "coaching", "feedback": ["x"]})
    variants = pipeline._build_image_team([d], team_niches=1, team_size=2)
    v1, v2 = variants
    assert (v1.design_id, v2.design_id) == ("D010-v1", "D010-v2")
    assert v1.parent_design_id == "D010"
    v1.review_history.append({"type": "note"})
    v1.brief["avoid"].append("only v1")
    v1.quality["image"] = {"status": "x"}
    assert len(v2.review_history) == 1 and "only v1" not in v2.brief["avoid"] and "image" not in v2.quality
    assert len(d.review_history) == 1
    assert v1.brief["variant_style"] != v2.brief["variant_style"]

    manager = ManagerAgent()
    d.compliance_status, d.product_type, d.unit_cost, d.price = "pass", "mug", 5, 20
    manager.score_and_decide([d])
    assert manager.score_for(v2) == manager.score_for(d) != {}


def test_live_prompt_agent_uses_brief_and_falls_back_to_template(monkeypatch):
    from app.live import gpt_agents

    monkeypatch.setattr(gpt_agents.openai_text, "is_configured", lambda: True)
    sent = []

    def fake_chat(system, user):
        sent.append(user)
        raise RuntimeError("API down")

    monkeypatch.setattr(gpt_agents.openai_text, "chat_json", fake_chat)
    d = _design(prompt="sleepy fox with a latte")
    gpt_agents.prompt_agent_live([d], product_types=("mug", "tote"))
    assert '"target_product": "mug"' in sent[0] and "reviewer_feedback" in sent[0]
    assert d.prompt == render_prompt(d.brief)
