from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.analytics_event import AnalyticsEvent
from app.models.message import Message
from app.models.user import User
from app.domain.monetization.config import MonetizationConfig
from app.services.monetization.dynamic_paywall import (
    apply_pricing_ladder,
    compute_segment,
    headline_for_segment,
    validate_trigger,
)
from app.services.monetization.paywalls import PaywallTrigger


def _session() -> Session:
    engine = create_engine("sqlite://", future=True, connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return Session(engine)


def _seed_users(db: Session) -> None:
    db.add(User(id=1, email="a@example.com", hashed_password="x", is_active=True, is_demo=False))
    db.add(User(id=2, email="b@example.com", hashed_password="x", is_active=True, is_demo=False))
    db.add(User(id=3, email="c@example.com", hashed_password="x", is_active=True, is_demo=False))
    db.commit()


def test_compute_segment_high_from_message_volume() -> None:
    db = _session()
    try:
        _seed_users(db)
        now = datetime.now(UTC)
        for i in range(8):
            db.add(Message(sender_id=1, receiver_id=2, content=f"m{i}", created_at=now - timedelta(hours=i)))
        db.commit()
        assert compute_segment(db, 1) == "high"
    finally:
        db.close()


def test_compute_segment_medium_from_browse_signal() -> None:
    db = _session()
    try:
        _seed_users(db)
        now = datetime.now(UTC)
        for i in range(9):
            db.add(
                AnalyticsEvent(
                    user_id=1,
                    name="discover_card_viewed",
                    created_at=now - timedelta(minutes=i),
                )
            )
        db.add(Message(sender_id=1, receiver_id=2, content="hi", created_at=now - timedelta(hours=1)))
        db.commit()
        assert compute_segment(db, 1) == "medium"
    finally:
        db.close()


def test_headlines_match_segments() -> None:
    assert "Unlock" in headline_for_segment("high")
    assert "matches" in headline_for_segment("medium").lower()
    assert "1 day" in headline_for_segment("low")


def test_pricing_ladder_first_vs_later() -> None:
    cfg = MonetizationConfig()
    first = apply_pricing_ladder({"offer_type": "trial", "trial_days": 3, "label": "t"}, 0, "high", cfg)
    later = apply_pricing_ladder({"offer_type": "trial", "trial_days": 3, "label": "t"}, 3, "high", cfg)
    assert int(first["discount_percent"]) >= int(later["discount_percent"])


def test_validate_chat_milestone_requires_depth() -> None:
    db = _session()
    try:
        _seed_users(db)
        now = datetime.now(UTC)
        db.add(Message(sender_id=1, receiver_id=2, content="a", created_at=now))
        db.commit()
        assert validate_trigger(db, 1, "chat_milestone", "chat_started") is False
        db.add(Message(sender_id=1, receiver_id=3, content="b", created_at=now))
        db.commit()
        assert validate_trigger(db, 1, "chat_milestone", "chat_started") is True
    finally:
        db.close()


def test_good_match_paywall_includes_dynamic_fields() -> None:
    db = _session()
    try:
        _seed_users(db)
        res = PaywallTrigger().trigger_paywall(db, 1, {"context": "good_match", "trigger": "good_match", "stage": "after_match"})
        assert res["show"] is True
        assert res["paywall_index"] == 0
        assert "trial_days" in res or "discount_percent" in res
    finally:
        db.close()
