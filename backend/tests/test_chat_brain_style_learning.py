from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.api.deps import get_admin_user, get_admin_actor
from app.api.v1.endpoints.admin import router as admin_router
from app.db.session import SessionLocal
from app.models.ai_interaction_event import AiInteractionEvent
from app.services.ai.chat_brain_style_profile import deep_extra_risk_from_profile, merge_profile_value
from app.services.ai.chat_brain_suggestions import _pick_recommended
from app.services.ai.memory import delete_user_ai_memory, get_user_ai_memory, log_ai_event


class DummyAdmin:
    id = 999
    email = "admin@example.com"


def _admin_client() -> TestClient:
    app = FastAPI()
    app.include_router(admin_router, prefix="/api/v1/admin")
    app.dependency_overrides[get_admin_user] = lambda: DummyAdmin()
    app.dependency_overrides[get_admin_actor] = lambda: DummyAdmin()
    return TestClient(app)


def _clear_user_and_events(db, user_id: int) -> None:
    db.execute(text("DELETE FROM ai_interaction_events WHERE user_id = :uid"), {"uid": user_id})
    db.execute(text("DELETE FROM user_ai_memory WHERE user_id = :uid"), {"uid": user_id})
    db.commit()


def test_cb_select_updates_pick_counts_and_preferred_tone():
    db = SessionLocal()
    try:
        _clear_user_and_events(db, 501)
        log_ai_event(db, user_id=501, partner_user_id=502, event_type="cb_select", metadata={"variant": "flirty"})
        log_ai_event(db, user_id=501, partner_user_id=502, event_type="cb_select", metadata={"variant": "flirty"})
        mem = get_user_ai_memory(db, user_id=501)
        val = mem["user_style"]["global"]["value"]
        assert float(val["pick_counts"]["flirty"]) >= 2.0
        assert val.get("preferred_tone") == "flirty"
    finally:
        db.close()


def test_cb_regen_increments_rejected_styles():
    db = SessionLocal()
    try:
        _clear_user_and_events(db, 503)
        log_ai_event(db, user_id=503, partner_user_id=504, event_type="cb_regen", metadata={"dropped_variant": "deep"})
        mem = get_user_ai_memory(db, user_id=503)
        assert float(mem["user_style"]["global"]["value"]["rejected_styles"]["deep"]) >= 0.5
    finally:
        db.close()


def test_partner_replied_chat_brain_syncs_success_counters():
    db = SessionLocal()
    try:
        _clear_user_and_events(db, 505)
        log_ai_event(
            db,
            user_id=505,
            partner_user_id=506,
            event_type="partner_replied",
            metadata={"previous_source": "chat_brain", "previous_style": "light", "reply_delay_minutes": 5},
        )
        mem = get_user_ai_memory(db, user_id=505)
        assert float(mem["user_style"]["global"]["value"]["successful_styles"]["light"]) >= 1.0
        assert float(mem["user_style"]["global"]["value"]["brain_reply_count"] or 0) >= 1.0
    finally:
        db.close()


def test_delete_memory_clears_style_profile_rows():
    db = SessionLocal()
    try:
        _clear_user_and_events(db, 507)
        log_ai_event(db, user_id=507, partner_user_id=508, event_type="cb_select", metadata={"variant": "deep"})
        deleted = delete_user_ai_memory(db, user_id=507)
        assert deleted >= 1
        mem = get_user_ai_memory(db, user_id=507)
        assert mem == {}
    finally:
        db.close()


def test_pick_recommended_respects_preferred_flirty():
    prof = merge_profile_value({"preferred_tone": "flirty", "successful_styles": {"light": 0, "flirty": 0, "deep": 0}})
    variants = {"light": "Hey?", "flirty": "Hi?", "deep": "So?"}
    insights = {k: {"risk": "neutral"} for k in variants}
    best, _ = _pick_recommended(variants, insights, "reply", 10, prof)
    assert best == "flirty"


def test_deep_extra_risk_from_rejection_history():
    prof = merge_profile_value({"rejected_styles": {"deep": 3.0}, "successful_styles": {"deep": 0.0}})
    assert deep_extra_risk_from_profile(prof, text_count=2) is True


def test_admin_chat_brain_style_aggregate_shape_no_message_bodies():
    db = SessionLocal()
    try:
        now = datetime.now(UTC)
        db.execute(text("DELETE FROM ai_interaction_events WHERE user_id = :u"), {"u": 601})
        db.commit()
        db.add(
            AiInteractionEvent(
                user_id=601,
                partner_user_id=602,
                event_type="cb_send",
                metadata_json={"variant": "flirty", "private_body": "should never appear in API"},
                created_at=now,
            )
        )
        db.add(
            AiInteractionEvent(
                user_id=601,
                partner_user_id=602,
                event_type="cb_reply",
                metadata_json={"variant": "flirty"},
                created_at=now + timedelta(seconds=1),
            )
        )
        db.commit()
    finally:
        db.close()

    c = _admin_client()
    res = c.get("/api/v1/admin/stats/chat-brain-style", params={"period": "7d"})
    assert res.status_code == 200
    j = res.json()
    assert j.get("note") == "aggregate_only_no_private_content"
    assert "private_body" not in str(j)
    assert isinstance(j.get("reply_after_brain_rate"), (int, float))
    assert j.get("brain_assisted_sends", 0) >= 1
    assert all(k in j for k in ("style_distribution_picks", "style_distribution_replies", "event_counts"))
