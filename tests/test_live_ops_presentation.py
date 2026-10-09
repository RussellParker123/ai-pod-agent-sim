from app.live_ops_presentation import (
    MANAGER_NODE,
    STAGE_NODES,
    STAGE_LOCATIONS,
    entry_status,
    registry_counts,
    render_live_console,
)
from app.sim.characters import DrCypher
from pathlib import Path

from streamlit.testing.v1 import AppTest


def test_live_console_renders_real_stage_statuses_and_escapes_logs():
    states = {key: "idle" for key, _, _ in STAGE_NODES + [MANAGER_NODE]}
    states.update(etsy_connect="active", trend="done", image="error")

    markup = render_live_console(states, ["<script>alert('x')</script>"])

    assert 'class="node active' in markup
    assert 'class="node done' in markup
    assert 'class="node error' in markup
    assert "IDLE" in markup
    assert "DR. CYPHER" in markup
    assert "&lt;script&gt;alert(&#x27;x&#x27;)&lt;/script&gt;" in markup
    assert "<script>" not in markup
    assert "LIVE OPS ARENA" in markup


def test_live_console_empty_state_and_unknown_status_are_safe():
    markup = render_live_console({}, [])

    assert "standing by..." in markup
    assert 'aria-label="TREND SCANNER: IDLE"' in markup
    assert "None" not in markup


def test_live_console_shows_character_avatar_and_live_event_dialogue_safely():
    character = DrCypher().to_dict()
    character.update(
        status="active",
        activity="Scouting <script>alert(1)</script>",
        line="Reviewing <design>",
    )

    markup = render_live_console({}, [], character)

    assert 'class="cypher-presence active"' in markup
    assert 'class="cypher-avatar" role="img" aria-label="Dr. Cypher"' in markup
    assert "<svg" in markup
    assert "Scouting &lt;script&gt;alert(1)&lt;/script&gt;" in markup
    assert "Reviewing &lt;design&gt;" in markup
    assert "<script>" not in markup
    assert STAGE_LOCATIONS["trend"] == "trend"
    assert STAGE_LOCATIONS["manager"] == "approval"


def test_registry_counts_only_explicit_local_statuses_and_handles_missing_fields():
    entries = [
        {"status": "pending_approval"},
        {"status": "live", "manager_score": None},
        {"status": "rejected", "rejection_reason": "review"},
        {},
    ]

    assert registry_counts(entries) == {
        "drafts": 1,
        "published": 1,
        "rejected": 1,
        "other": 1,
    }
    assert entry_status(entries[0]) == "Draft · awaiting review"
    assert entry_status(entries[1]) == "Published"
    assert entry_status(entries[2]) == "Rejected"
    assert entry_status(entries[3]) == "Other recorded status"
    assert registry_counts([]) == {"drafts": 0, "published": 0, "rejected": 0, "other": 0}


def test_registry_status_does_not_infer_sales_or_revenue_from_listing_price():
    entry = {"status": "pending_approval", "price": 24.99}

    assert entry_status(entry) == "Draft · awaiting review"
    assert "revenue" not in registry_counts([entry])
    assert "profit" not in registry_counts([entry])


def test_disconnected_page_shows_guidance_and_never_starts_live_actions(monkeypatch):
    from app.integrations import etsy_auth
    from app.live import pipeline

    calls = []
    monkeypatch.setattr(etsy_auth, "is_connected", lambda: False)
    monkeypatch.setattr(pipeline, "run_live_batch_stream", lambda **_: calls.append("batch"))
    monkeypatch.setattr(pipeline, "approve_and_publish", lambda *_: calls.append("publish"))
    monkeypatch.setattr(pipeline, "reject", lambda *_args, **_kwargs: calls.append("reject"))

    app_path = Path(__file__).parents[1] / "app" / "pages" / "4_Live_Ops.py"
    app = AppTest.from_file(str(app_path)).run()

    rendered_text = "\n".join(element.value for element in list(app.info) + list(app.warning))
    assert "Connect your Etsy shop first" in rendered_text
    assert "LIVE Etsy work" in rendered_text
    assert calls == []
    assert not app.exception


def test_connected_empty_page_does_not_execute_any_action_on_render(monkeypatch):
    from app.integrations import etsy_auth, openai_image, printful_client
    from app.live import order_sync, pipeline

    calls = []
    monkeypatch.setattr(etsy_auth, "is_connected", lambda: True)
    monkeypatch.setattr(openai_image, "is_configured", lambda: False)
    monkeypatch.setattr(printful_client, "is_configured", lambda: False)
    monkeypatch.setattr(pipeline, "list_all", lambda: [])
    monkeypatch.setattr(pipeline, "list_pending", lambda: [])
    monkeypatch.setattr(pipeline, "list_image_archive", lambda: [])
    monkeypatch.setattr(pipeline, "run_live_batch_stream", lambda **_: calls.append("batch"))
    monkeypatch.setattr(pipeline, "approve_and_publish", lambda *_: calls.append("publish"))
    monkeypatch.setattr(pipeline, "reject", lambda *_args, **_kwargs: calls.append("reject"))
    monkeypatch.setattr(pipeline, "hold_archive_image_for_reuse", lambda *_: calls.append("reuse"))
    monkeypatch.setattr(pipeline, "stage_archived_image", lambda **_: calls.append("stage"))
    monkeypatch.setattr(order_sync, "sync_new_orders", lambda: calls.append("sync"))

    app_path = Path(__file__).parents[1] / "app" / "pages" / "4_Live_Ops.py"
    app = AppTest.from_file(str(app_path)).run()

    assert not app.exception
    assert app.number_input[0].value == 6
    assert app.checkbox[0].value is False
    assert calls == []
