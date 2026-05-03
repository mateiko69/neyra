from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import app.core.config as cfg
from app.db.base import Base
from app.models.analytics_event import AnalyticsEvent
from app.models.match import Match
from app.models.message import Message
from app.models.profile import Profile
from app.models.user import User
from app.services import demo_behavior as dbh
from app.services.demo_behavior import _aware_utc
from app.services.demo_mode import set_demo_live_settings, set_demo_mode_enabled


def _memory_session() -> Session:
    engine = create_engine(
        "sqlite://",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return Session(engine)


def _seed_demo_match(db: Session) -> None:
    db.add(User(id=1, email="real@example.com", hashed_password="x", is_active=True, is_demo=False))
    db.add(User(id=2, email="demo@neyra.local", hashed_password=None, is_active=True, is_demo=True))
    db.add(
        Profile(
            user_id=1,
            display_name="Real",
            bio="real",
            age=27,
            city="Kyiv",
            gender="man",
            interested_in="women",
            onboarding_completed=True,
            is_demo_profile=False,
        )
    )
    pers = {
        "personality": "curious",
        "response_speed": "normal",
        "engagement_level": 0.8,
        "opener_examples": ["Hello from example opener"],
        "reply_examples": ["Reply from example"],
        "revive_examples": ["Revive example"],
    }
    db.add(
        Profile(
            user_id=2,
            display_name="Dee",
            bio="demo",
            age=25,
            city="Kyiv",
            gender="woman",
            interested_in="men",
            is_demo_profile=True,
            demo_personality_json=json.dumps(pers),
        )
    )
    db.add(Match(user_a_id=1, user_b_id=2))
    db.commit()


def test_live_disabled_without_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cfg.settings, "DEMO_LIVE_BEHAVIOR", False)
    db = _memory_session()
    try:
        _seed_demo_match(db)
        set_demo_mode_enabled(db, True)
        set_demo_live_settings(db, enabled=True)
        from app.services.demo_mode import is_demo_live_enabled

        assert is_demo_live_enabled(db) is False
    finally:
        db.close()


def test_schedule_first_message_not_instant(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cfg.settings, "DEMO_LIVE_BEHAVIOR", True)
    db = _memory_session()
    try:
        _seed_demo_match(db)
        set_demo_mode_enabled(db, True)
        set_demo_live_settings(db, enabled=True)
        monkeypatch.setattr(dbh.random, "random", lambda: 0.0)
        dbh.schedule_demo_first_message_maybe(db, 2, 1)
        p = db.query(Profile).filter(Profile.user_id == 2).first()
        assert p is not None
        assert p.demo_reply_scheduled_at is not None
        delta = (_aware_utc(p.demo_reply_scheduled_at) - datetime.now(UTC)).total_seconds()
        assert 35 <= delta <= 160
        assert db.query(Message).filter(Message.sender_id == 2).count() == 0
    finally:
        db.close()


def test_note_real_user_schedules_delay_not_instant(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cfg.settings, "DEMO_LIVE_BEHAVIOR", True)
    db = _memory_session()
    try:
        _seed_demo_match(db)
        set_demo_mode_enabled(db, True)
        set_demo_live_settings(db, enabled=True)
        monkeypatch.setattr(dbh.random, "random", lambda: 0.99)
        db.add(Message(sender_id=1, receiver_id=2, content="hi"))
        db.commit()
        dbh.note_real_user_message_to_demo(db, 2, 1)
        p = db.query(Profile).filter(Profile.user_id == 2).first()
        assert p.demo_reply_scheduled_at is not None
        assert _aware_utc(p.demo_reply_scheduled_at) > datetime.now(UTC)
        assert db.query(Message).filter(Message.sender_id == 2).count() == 0
    finally:
        db.close()


def test_real_user_message_schedules_demo_reply(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cfg.settings, "DEMO_LIVE_BEHAVIOR", True)
    db = _memory_session()
    try:
        _seed_demo_match(db)
        set_demo_mode_enabled(db, True)
        set_demo_live_settings(db, enabled=True)
        db.add(Message(sender_id=1, receiver_id=2, content="hi"))
        db.commit()
        dbh.note_real_user_message_to_demo(db, 2, 1)
        p = db.query(Profile).filter(Profile.user_id == 2).first()
        assert p.demo_reply_scheduled_at is not None
    finally:
        db.close()


def test_deliver_reply_uses_example_and_marks_demo(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cfg.settings, "DEMO_LIVE_BEHAVIOR", True)
    db = _memory_session()
    try:
        _seed_demo_match(db)
        set_demo_mode_enabled(db, True)
        set_demo_live_settings(db, enabled=True)
        p = db.query(Profile).filter(Profile.user_id == 2).first()
        dbh._set_pending(p, 1, "reply", datetime.now(UTC) - timedelta(seconds=5))
        db.add(p)
        db.commit()
        demo_u = db.query(User).filter(User.id == 2).first()
        dbh._deliver_pending(db, p, demo_u)
        m = db.query(Message).filter(Message.sender_id == 2, Message.receiver_id == 1).first()
        assert m is not None
        assert m.is_demo_simulation is True
        assert len((m.content or "").strip()) > 12
        assert "?" in (m.content or "") or "？" in (m.content or "")
        assert db.query(AnalyticsEvent).filter(AnalyticsEvent.name == "demo_reply_sent").count() == 1
    finally:
        db.close()


def test_second_deliver_does_not_duplicate(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cfg.settings, "DEMO_LIVE_BEHAVIOR", True)
    db = _memory_session()
    try:
        _seed_demo_match(db)
        set_demo_mode_enabled(db, True)
        set_demo_live_settings(db, enabled=True)
        p = db.query(Profile).filter(Profile.user_id == 2).first()
        dbh._set_pending(p, 1, "reply", datetime.now(UTC) - timedelta(seconds=5))
        db.add(p)
        db.commit()
        demo_u = db.query(User).filter(User.id == 2).first()
        dbh._deliver_pending(db, p, demo_u)
        p2 = db.query(Profile).filter(Profile.user_id == 2).first()
        dbh._deliver_pending(db, p2, demo_u)
        assert db.query(Message).filter(Message.sender_id == 2).count() == 1
    finally:
        db.close()


def test_user_sent_first_message_cancels_scheduled_first_opener(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cfg.settings, "DEMO_LIVE_BEHAVIOR", True)
    db = _memory_session()
    try:
        _seed_demo_match(db)
        set_demo_mode_enabled(db, True)
        set_demo_live_settings(db, enabled=True)
        dbh.schedule_demo_first_message_maybe(db, 2, 1)
        # User sends first before opener fires.
        db.add(Message(sender_id=1, receiver_id=2, content="hi first"))
        db.commit()
        p = db.query(Profile).filter(Profile.user_id == 2).first()
        p.demo_reply_scheduled_at = datetime.now(UTC) - timedelta(seconds=1)
        db.add(p)
        db.commit()
        demo_u = db.query(User).filter(User.id == 2).first()
        dbh._deliver_pending(db, p, demo_u)
        assert db.query(Message).filter(Message.sender_id == 2, Message.receiver_id == 1).count() == 0
    finally:
        db.close()


def test_passed_user_blocks_scheduled_auto_opener(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cfg.settings, "DEMO_LIVE_BEHAVIOR", True)
    db = _memory_session()
    try:
        _seed_demo_match(db)
        set_demo_mode_enabled(db, True)
        set_demo_live_settings(db, enabled=True)
        dbh.schedule_demo_first_message_maybe(db, 2, 1)
        # User pass/dislike after scheduling.
        from app.models.swipe import Swipe

        db.add(Swipe(swiper_id=1, target_user_id=2, liked=False))
        db.commit()
        p = db.query(Profile).filter(Profile.user_id == 2).first()
        p.demo_reply_scheduled_at = datetime.now(UTC) - timedelta(seconds=1)
        db.add(p)
        db.commit()
        demo_u = db.query(User).filter(User.id == 2).first()
        dbh._deliver_pending(db, p, demo_u)
        assert db.query(Message).filter(Message.sender_id == 2, Message.receiver_id == 1).count() == 0
    finally:
        db.close()


def test_direct_question_reply_answers_first_then_followup(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cfg.settings, "DEMO_LIVE_BEHAVIOR", True)
    db = _memory_session()
    try:
        _seed_demo_match(db)
        set_demo_mode_enabled(db, True)
        set_demo_live_settings(db, enabled=True)
        inbound = Message(sender_id=1, receiver_id=2, content="Скільки тобі років?")
        db.add(inbound)
        db.commit()
        db.refresh(inbound)

        monkeypatch.setattr(
            "app.services.ai.orchestrator.AIOrchestrator.generate_demo_reply",
            staticmethod(lambda **_: "Мені 25"),
        )

        dbh.note_real_user_message_to_demo(db, 2, 1, trigger_message_id=int(inbound.id))
        p = db.query(Profile).filter(Profile.user_id == 2).first()
        p.demo_reply_scheduled_at = datetime.now(UTC) - timedelta(seconds=1)
        db.add(p)
        db.commit()
        demo_u = db.query(User).filter(User.id == 2).first()
        dbh._deliver_pending(db, p, demo_u)
        out = (
            db.query(Message)
            .filter(Message.sender_id == 2, Message.receiver_id == 1)
            .order_by(Message.created_at.desc())
            .first()
        )
        assert out is not None
        txt = str(out.content or "")
        assert txt.startswith("Мені 25")
        assert "?" in txt or "А в тебе як із цим" in txt
    finally:
        db.close()


def test_same_trigger_message_id_skips_duplicate_reply(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cfg.settings, "DEMO_LIVE_BEHAVIOR", True)
    monkeypatch.setattr(cfg.settings, "DEMO_BOT_REPLY_DELAY_SECONDS", -1)
    db = _memory_session()
    try:
        _seed_demo_match(db)
        set_demo_mode_enabled(db, True)
        set_demo_live_settings(db, enabled=True)
        trigger = Message(sender_id=1, receiver_id=2, content="hello")
        db.add(trigger)
        db.commit()
        db.refresh(trigger)
        dbh.note_real_user_message_to_demo(db, 2, 1, trigger_message_id=int(trigger.id))
        demo_u = db.query(User).filter(User.id == 2).first()
        p = db.query(Profile).filter(Profile.user_id == 2).first()
        dbh._deliver_pending(db, p, demo_u)
        # same trigger should be ignored
        dbh.note_real_user_message_to_demo(db, 2, 1, trigger_message_id=int(trigger.id))
        p2 = db.query(Profile).filter(Profile.user_id == 2).first()
        dbh._deliver_pending(db, p2, demo_u)
        rows = db.query(Message).filter(Message.sender_id == 2, Message.receiver_id == 1).all()
        assert len(rows) == 1
    finally:
        db.close()


def test_demo_bot_chat_disabled_prevents_reply(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cfg.settings, "DEMO_LIVE_BEHAVIOR", True)
    monkeypatch.setattr(cfg.settings, "DEMO_BOT_CHAT_ENABLED", False)
    db = _memory_session()
    try:
        _seed_demo_match(db)
        set_demo_mode_enabled(db, True)
        set_demo_live_settings(db, enabled=True)
        dbh.note_real_user_message_to_demo(db, 2, 1, trigger_message_id=123)
        p = db.query(Profile).filter(Profile.user_id == 2).first()
        assert p.demo_reply_scheduled_at is None
    finally:
        db.close()


def test_real_user_message_not_flagged_demo() -> None:
    db = _memory_session()
    try:
        db.add(User(id=1, email="a@example.com", hashed_password="x", is_active=True, is_demo=False))
        db.add(User(id=2, email="b@example.com", hashed_password="x", is_active=True, is_demo=False))
        db.add(Message(sender_id=1, receiver_id=2, content="x"))
        db.commit()
        m = db.query(Message).first()
        assert m.is_demo_simulation is False
    finally:
        db.close()


def test_onboarding_incomplete_does_not_schedule_demo_first_message(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cfg.settings, "DEMO_LIVE_BEHAVIOR", True)
    db = _memory_session()
    try:
        _seed_demo_match(db)
        # Mark real user as not onboarded.
        p_real = db.query(Profile).filter(Profile.user_id == 1).first()
        p_real.onboarding_completed = False
        db.add(p_real)
        db.commit()
        set_demo_mode_enabled(db, True)
        set_demo_live_settings(db, enabled=True)
        dbh.schedule_demo_first_message_maybe(db, 2, 1)
        p_demo = db.query(Profile).filter(Profile.user_id == 2).first()
        assert p_demo.demo_reply_scheduled_at is None
    finally:
        db.close()


def test_onboarding_complete_allows_demo_first_message(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cfg.settings, "DEMO_LIVE_BEHAVIOR", True)
    db = _memory_session()
    try:
        _seed_demo_match(db)
        set_demo_mode_enabled(db, True)
        set_demo_live_settings(db, enabled=True)
        dbh.schedule_demo_first_message_maybe(db, 2, 1)
        p_demo = db.query(Profile).filter(Profile.user_id == 2).first()
        assert p_demo.demo_reply_scheduled_at is not None
    finally:
        db.close()


def test_demo_push_skipped_for_demo_receiver() -> None:
    from app.services.notifications import send_user_notification

    db = _memory_session()
    try:
        db.add(User(id=1, email="d@neyra.local", hashed_password=None, is_active=True, is_demo=True))
        db.commit()
        out = send_user_notification(db, 1, "t", "b")
        assert out == []
    finally:
        db.close()


def test_demo_behavior_tick_does_not_crash_on_missing_timezone() -> None:
    db = _memory_session()
    try:
        # Demo profile with naive scheduled_at (SQLite-style) must not crash comparisons.
        db.add(User(id=10, email="demo10@neyra.local", hashed_password=None, is_active=True, is_demo=True))
        db.add(
            Profile(
                user_id=10,
                display_name="Demo10",
                bio="demo",
                age=25,
                city="Kyiv",
                gender="woman",
                interested_in="men",
                is_demo_profile=True,
                demo_reply_scheduled_at=datetime.utcnow(),  # naive
            )
        )
        db.commit()
        # Should not raise.
        out = dbh.run_demo_behavior_tick(db)
        assert isinstance(out, dict)
    finally:
        db.close()
