from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.db.base import Base
from app.models.subscription import Subscription
from app.models.user import User
from app.services.monetization.subscription_service import SubscriptionService
from app.services.premium import is_user_premium


def _memory_db() -> Session:
    engine = create_engine(
        "sqlite://",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return Session(engine)


def test_dev_force_premium_true_makes_user_premium(monkeypatch):
    monkeypatch.setattr(settings, "DEV_FORCE_PREMIUM", True)
    monkeypatch.setattr(settings, "ENV", "development")
    db = _memory_db()
    try:
        u = User(email="u@example.com", hashed_password="x", is_active=True)
        db.add(u)
        db.commit()
        assert is_user_premium(db, int(u.id)) is True
        assert SubscriptionService().get_active_plan(db, int(u.id)) == "premium_plus"
    finally:
        db.close()


def test_dev_force_premium_ignored_in_production(monkeypatch):
    monkeypatch.setattr(settings, "DEV_FORCE_PREMIUM", True)
    monkeypatch.setattr(settings, "ENV", "production")
    db = _memory_db()
    try:
        u = User(email="u2@example.com", hashed_password="x", is_active=True)
        db.add(u)
        db.commit()
        assert is_user_premium(db, int(u.id)) is False
        assert SubscriptionService().get_active_plan(db, int(u.id)) == "free"
    finally:
        db.close()


def test_normal_premium_logic_still_works_when_flag_off(monkeypatch):
    monkeypatch.setattr(settings, "DEV_FORCE_PREMIUM", False)
    monkeypatch.setattr(settings, "ENV", "development")
    db = _memory_db()
    try:
        u = User(email="paid@example.com", hashed_password="x", is_active=True)
        db.add(u)
        db.flush()
        db.add(Subscription(user_id=int(u.id), status="active", plan_code="premium_plus"))
        db.commit()
        assert is_user_premium(db, int(u.id)) is True
        assert SubscriptionService().get_active_plan(db, int(u.id)) in {"premium_plus", "premium"}
    finally:
        db.close()

