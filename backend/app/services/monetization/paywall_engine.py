from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.domain.growth.config import DEFAULT_GROWTH_CONFIG, GrowthConfig
from app.models.analytics_event import AnalyticsEvent
from app.services.monetization.premium_engine import PremiumEngine


@dataclass(frozen=True)
class PaywallDecision:
    show: bool
    message: str
    offer_type: str

    def to_dict(self) -> dict:
        return {"show": self.show, "message": self.message, "offer_type": self.offer_type}


class PaywallEngine:
    """Soft paywalls (guide behavior, not lock core experience)."""

    def __init__(self, config: GrowthConfig = DEFAULT_GROWTH_CONFIG):
        self._c = config
        self._premium = PremiumEngine()

    def trigger_paywall(self, db: Session, user_id: int, context: dict) -> PaywallDecision:
        ctype = (context.get("type") or "").strip()
        now = datetime.now(UTC)
        day_ago = now - timedelta(days=1)

        if ctype == "ai_replies":
            access = self._premium.check_feature_access(db, user_id, "unlimited_ai_suggestions")
            if access.get("allowed"):
                return PaywallDecision(False, "", "subscription")
            used = (
                db.query(AnalyticsEvent)
                .filter((AnalyticsEvent.user_id == user_id) & (AnalyticsEvent.name == "ai_reply_generated") & (AnalyticsEvent.created_at >= day_ago))
                .count()
            )
            if used >= self._c.free_ai_reply_limit_per_day:
                return PaywallDecision(True, "Хочеш більше варіантів відповіді? Відкрий безліміт AI-підказок.", "subscription")

        if ctype == "advanced_insights":
            access = self._premium.check_feature_access(db, user_id, "advanced_compatibility_insights")
            if not access.get("allowed"):
                return PaywallDecision(True, "Глибші інсайти про сумісність доступні в Premium.", "trial")

        if ctype == "low_replies_unlock_ai":
            access = self._premium.check_feature_access(db, user_id, "conversation_coach_insights")
            if not access.get("allowed"):
                return PaywallDecision(True, "Хочеш підняти reply rate? Відкрий коуч-поради для діалогів.", "trial")

        return PaywallDecision(False, "", "subscription")

