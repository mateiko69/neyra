from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.analytics_event import AnalyticsEvent
from app.models.message import Message
from app.models.user import User
from app.services.monetization.access import MonetizationAccess
from app.services.monetization.paywalls import PaywallTrigger
from app.services.monetization.offers import OfferEngine


class FakeQuery:
    def __init__(self, count_value: int = 0, first_value=None):
        self._count_value = count_value
        self._first_value = first_value

    def filter(self, *_args, **_kwargs):
        return self

    def count(self):
        return self._count_value

    def first(self):
        return self._first_value


class FakeSub:
    def __init__(self, status="inactive", plan_code="free", start_date=None, end_date=None):
        self.status = status
        self.plan_code = plan_code
        self.start_date = start_date
        self.end_date = end_date


class FakeDB:
    def __init__(self, sub=None, counts=None):
        self.sub = sub
        self.counts = counts or {}

    def query(self, model):
        name = getattr(model, "__name__", str(model))
        if name == "Subscription":
            return FakeQuery(first_value=self.sub)
        return FakeQuery(count_value=self.counts.get(name, 0))


def test_free_user_blocked_for_premium_feature():
    db = FakeDB(sub=FakeSub(status="inactive", plan_code="free"))
    res = MonetizationAccess().check_access(db, 1, "ai_unlimited_replies")
    assert res["allowed"] is False
    assert res["upgrade_required"] is True


def test_paywall_respects_cooldown():
    # If paywall_shown count >=1 in cooldown window -> no show
    db = FakeDB(sub=FakeSub(status="inactive", plan_code="free"), counts={"AnalyticsEvent": 1})
    res = PaywallTrigger().trigger_paywall(db, 1, {"context": "reply_suggestion_request"})
    assert res["show"] is False


def _session() -> Session:
    engine = create_engine("sqlite://", future=True, connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return Session(engine)


def test_soft_paywall_contexts_return_benefits():
    db = _session()
    try:
        db.add(User(id=1, email="a@example.com", hashed_password="x", is_active=True, is_demo=False))
        db.add(User(id=2, email="b@example.com", hashed_password="x", is_active=True, is_demo=False))
        db.commit()
        res = PaywallTrigger().trigger_paywall(db, 1, {"context": "good_match", "stage": "value_visible", "trigger": "good_match"})
        assert res["show"] is True
        assert "benefits" in res
        assert isinstance(res["benefits"], list)
        assert res.get("segment") in {"high", "medium", "low"}
        assert res.get("trigger") == "good_match"
    finally:
        db.close()

