import json

from sqlalchemy import text

from app.db.session import SessionLocal
from app.services.ai.memory import (
    PERSONALIZATION_MAX_BYTES,
    delete_user_ai_memory,
    get_personalization_context,
    get_user_ai_memory,
    log_ai_event,
)


def _clear(db):
    db.execute(text("DELETE FROM ai_interaction_events"))
    db.execute(text("DELETE FROM user_ai_memory"))
    db.commit()


def test_option_selected_updates_preferred_style():
    db = SessionLocal()
    try:
        _clear(db)
        log_ai_event(db, user_id=1, partner_user_id=2, event_type="option_selected", metadata={"style": "flirty", "option_index": 1})
        mem = get_user_ai_memory(db, user_id=1)
        assert mem["user_style"]["global"]["value"]["preferred_tone"] == "flirty"
    finally:
        db.close()


def test_partner_replied_increases_success_weight():
    db = SessionLocal()
    try:
        _clear(db)
        log_ai_event(db, user_id=1, partner_user_id=2, event_type="partner_replied", metadata={"previous_style": "light", "reply_delay_minutes": 10})
        mem = get_user_ai_memory(db, user_id=1)
        assert mem["successful_openers"]["global"]["value"]["light_success"] >= 1.0
    finally:
        db.close()


def test_option_edited_high_reduces_confidence():
    db = SessionLocal()
    try:
        _clear(db)
        log_ai_event(db, user_id=1, partner_user_id=2, event_type="option_selected", metadata={"style": "light"})
        before = get_user_ai_memory(db, user_id=1)["user_style"]["global"]["confidence"]
        log_ai_event(db, user_id=1, partner_user_id=2, event_type="option_edited", metadata={"edit_distance_level": "high"})
        after = get_user_ai_memory(db, user_id=1)["user_style"]["global"]["confidence"]
        assert after <= before
    finally:
        db.close()


def test_meeting_rejected_updates_preferences():
    db = SessionLocal()
    try:
        _clear(db)
        log_ai_event(db, user_id=1, partner_user_id=2, event_type="meeting_rejected", metadata={})
        mem = get_user_ai_memory(db, user_id=1)
        assert mem["dating_preferences"]["global"]["value"]["avoids_direct_meeting_too_early"] is True
    finally:
        db.close()


def test_delete_memory_clears():
    db = SessionLocal()
    try:
        _clear(db)
        log_ai_event(db, user_id=1, partner_user_id=2, event_type="option_selected", metadata={"style": "flirty"})
        deleted = delete_user_ai_memory(db, user_id=1)
        assert deleted >= 1
        mem = get_user_ai_memory(db, user_id=1)
        assert mem == {}
    finally:
        db.close()


def test_personalization_summary_merges_and_caps():
    db = SessionLocal()
    try:
        _clear(db)
        log_ai_event(
            db,
            user_id=91,
            partner_user_id=92,
            event_type="option_selected",
            metadata={"style": "deep", "interests": ["travel"], "memory_hint": "reach me at user@mail.com"},
            thread_id="t-1",
        )
        mem = get_user_ai_memory(db, user_id=91)
        summary = mem["personalization"]["summary"]["value"]
        assert summary["tone_preference"] == "deep"
        assert "travel" in summary["interests"]
        assert "@" not in "".join(summary.get("notes") or [])
        raw = json.dumps(summary, ensure_ascii=False).encode("utf-8")
        assert len(raw) <= PERSONALIZATION_MAX_BYTES
        ctx = get_personalization_context(db, user_id=91)
        assert "summary_json" in ctx
        assert ctx["summary_json"]["tone_preference"] == "deep"
    finally:
        db.close()


def test_edited_event_matches_option_edited_learning():
    db = SessionLocal()
    try:
        _clear(db)
        log_ai_event(db, user_id=81, partner_user_id=82, event_type="option_selected", metadata={"style": "light"})
        before = get_user_ai_memory(db, user_id=81)["user_style"]["global"]["confidence"]
        log_ai_event(db, user_id=81, partner_user_id=82, event_type="edited", metadata={"edit_distance_level": "high"})
        after = get_user_ai_memory(db, user_id=81)["user_style"]["global"]["confidence"]
        assert after <= before
    finally:
        db.close()

