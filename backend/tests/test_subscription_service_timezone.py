"""Subscription period checks must not crash on naive vs aware datetimes from the DB."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.db.base import Base
from app.models.subscription import Subscription
from app.models.user import User
from app.services.monetization.subscription_service import SubscriptionService
from app.utils.datetime_utc import to_utc_aware


def _memory_db() -> Session:
    engine = create_engine(
        "sqlite://",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return Session(engine)


def test_to_utc_aware_none():
    assert to_utc_aware(None) is None


def test_to_utc_aware_naive_becomes_utc():
    d = datetime(2024, 6, 1, 12, 0, 0)
    out = to_utc_aware(d)
    assert out is not None
    assert out.tzinfo is UTC
    assert out.replace(tzinfo=None) == d


def test_to_utc_aware_other_tz_converts_to_utc():
    from datetime import timezone as tz

    d = datetime(2024, 6, 1, 12, 0, 0, tzinfo=tz(timedelta(hours=2)))
    out = to_utc_aware(d)
    assert out is not None
    assert out.tzinfo is UTC
    assert out.hour == 10  # 12:00 +02 -> 10:00 UTC


def test_get_active_plan_naive_dates_active_period(monkeypatch):
    monkeypatch.setattr(settings, "DEV_FORCE_PREMIUM", False)
    monkeypatch.setattr(settings, "ENV", "development")
    db = _memory_db()
    try:
        u = User(email="naive@example.com", hashed_password="x", is_active=True)
        db.add(u)
        db.flush()
        db.add(
            Subscription(
                user_id=int(u.id),
                status="active",
                plan_code="premium",
                start_date=datetime.now(UTC).replace(tzinfo=None) - timedelta(days=1),
                end_date=datetime.now(UTC).replace(tzinfo=None) + timedelta(days=30),
            )
        )
        db.commit()
        assert SubscriptionService().get_active_plan(db, int(u.id)) == "premium"
    finally:
        db.close()


def test_get_active_plan_naive_future_start_returns_free(monkeypatch):
    monkeypatch.setattr(settings, "DEV_FORCE_PREMIUM", False)
    monkeypatch.setattr(settings, "ENV", "development")
    db = _memory_db()
    try:
        u = User(email="future@example.com", hashed_password="x", is_active=True)
        db.add(u)
        db.flush()
        db.add(
            Subscription(
                user_id=int(u.id),
                status="active",
                plan_code="premium_plus",
                start_date=datetime(2035, 1, 1, 0, 0, 0),
                end_date=datetime(2036, 1, 1, 0, 0, 0),
            )
        )
        db.commit()
        assert SubscriptionService().get_active_plan(db, int(u.id)) == "free"
    finally:
        db.close()


def test_get_active_plan_naive_past_end_returns_free(monkeypatch):
    monkeypatch.setattr(settings, "DEV_FORCE_PREMIUM", False)
    monkeypatch.setattr(settings, "ENV", "development")
    db = _memory_db()
    try:
        u = User(email="expired@example.com", hashed_password="x", is_active=True)
        db.add(u)
        db.flush()
        db.add(
            Subscription(
                user_id=int(u.id),
                status="active",
                plan_code="premium",
                start_date=datetime(2020, 1, 1, 0, 0, 0),
                end_date=datetime(2020, 2, 1, 0, 0, 0),
            )
        )
        db.commit()
        assert SubscriptionService().get_active_plan(db, int(u.id)) == "free"
    finally:
        db.close()


def test_get_active_plan_aware_dates_no_crash(monkeypatch):
    monkeypatch.setattr(settings, "DEV_FORCE_PREMIUM", False)
    monkeypatch.setattr(settings, "ENV", "development")
    db = _memory_db()
    try:
        u = User(email="aware@example.com", hashed_password="x", is_active=True)
        db.add(u)
        db.flush()
        now = datetime.now(UTC)
        db.add(
            Subscription(
                user_id=int(u.id),
                status="active",
                plan_code="premium_plus",
                start_date=now - timedelta(days=2),
                end_date=now + timedelta(days=28),
            )
        )
        db.commit()
        assert SubscriptionService().get_active_plan(db, int(u.id)) == "premium_plus"
    finally:
        db.close()


def test_get_active_plan_no_dates_returns_plan(monkeypatch):
    monkeypatch.setattr(settings, "DEV_FORCE_PREMIUM", False)
    monkeypatch.setattr(settings, "ENV", "development")
    db = _memory_db()
    try:
        u = User(email="nodate@example.com", hashed_password="x", is_active=True)
        db.add(u)
        db.flush()
        db.add(
            Subscription(
                user_id=int(u.id),
                status="active",
                plan_code="premium",
                start_date=None,
                end_date=None,
            )
        )
        db.commit()
        assert SubscriptionService().get_active_plan(db, int(u.id)) == "premium"
    finally:
        db.close()
