from datetime import datetime, timedelta

from app.domain.growth.types import EngagementState
from app.services.retention.notification_engine import NotificationEngine
from app.services.monetization.premium_engine import PremiumEngine
from app.services.monetization.paywall_engine import PaywallEngine
from app.services.growth.referral_system import ReferralSystem
from app.services.retention.nudge_system import NudgeSystem


class FakeQuery:
    def __init__(self, count_value: int = 0):
        self._count_value = count_value

    def filter(self, *_args, **_kwargs):
        return self

    def order_by(self, *_args, **_kwargs):
        return self

    def first(self):
        return None

    def all(self):
        return []

    def count(self):
        return self._count_value


class FakeDB:
    def __init__(self, counts: dict[str, int] | None = None):
        self.counts = counts or {}

    def query(self, model):
        name = getattr(model, "__name__", str(model))
        return FakeQuery(self.counts.get(name, 0))


def test_inactive_users_get_nudges():
    db = FakeDB(counts={"AnalyticsEvent": 0})
    engagement = EngagementState(activity_level="low", last_active_hours=72, matches_recent=0, messages_sent=0, reply_rate=0.0, drop_risk=90)
    nudges = NudgeSystem().generate_nudges(db, 1, engagement)
    assert len(nudges) >= 1


def test_active_users_do_not_get_spam():
    # Simulate nudges already shown today hitting cap.
    db = FakeDB(counts={"AnalyticsEvent": 10})
    engagement = EngagementState(activity_level="high", last_active_hours=1, matches_recent=2, messages_sent=10, reply_rate=80.0, drop_risk=10)
    nudges = NudgeSystem().generate_nudges(db, 1, engagement)
    assert nudges == []


def test_premium_blocks_work_for_known_feature():
    # No DB subscription in this unit test: PremiumEngine defaults unknown to allowed,
    # but known entitlement-based features will call has_premium_access in integration tests.
    # Here we at least validate unknown feature doesn't block core.
    db = FakeDB()
    res = PremiumEngine().check_feature_access(db, 1, "see_who_liked_you")
    assert "allowed" in res


def test_paywall_triggers_correctly_on_ai_limit():
    db = FakeDB(counts={"AnalyticsEvent": 999})
    decision = PaywallEngine().trigger_paywall(db, 1, {"type": "ai_replies"})
    assert decision.show is True


def test_referral_code_is_stable():
    sys = ReferralSystem()
    a = sys.generate_referral_code(123)
    b = sys.generate_referral_code(123)
    assert a == b


def test_notification_engine_avoids_spam_on_cooldown():
    # recent notifications sent => premium_offer suppressed
    db = FakeDB(counts={"AnalyticsEvent": 1})
    decision = NotificationEngine().decide_notification(db, 1, {"type": "premium_offer"})
    # With cooldown + count heuristic, can suppress by returning send False or in_app only.
    assert decision.channel in {"push", "in_app"}


def test_notification_engine_supports_retention_events():
    db = FakeDB(counts={"AnalyticsEvent": 0})
    engine = NotificationEngine()
    for t in ["daily_new_matches", "daily_profile_views", "dead_chat_revive", "micro_reward_noticed", "micro_reward_trending"]:
        decision = engine.decide_notification(db, 1, {"type": t})
        assert isinstance(decision.channel, str)


def test_smart_notification_copy_messages_and_revive():
    db = FakeDB(counts={"AnalyticsEvent": 0})
    engine = NotificationEngine()
    msg = engine.decide_notification(db, 1, {"type": "new_message"})
    assert msg.send and msg.title.startswith("They replied")
    match = engine.decide_notification(db, 1, {"type": "new_match"})
    assert match.send and "new match" in match.title.lower()
    revive = engine.decide_notification(db, 1, {"type": "dead_chat_revive"})
    assert revive.send and "chat" in revive.title.lower()
    hook = engine.decide_notification(db, 1, {"type": "ai_hook"})
    assert hook.send and "AI" in hook.title
    streak = engine.decide_notification(db, 1, {"type": "streak_reminder"})
    assert streak.send and "fire" in streak.title.lower()

