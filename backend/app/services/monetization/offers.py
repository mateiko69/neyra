from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.domain.monetization.config import DEFAULT_MONETIZATION_CONFIG, MonetizationConfig
from app.models.analytics_event import AnalyticsEvent
from app.services.monetization.subscription_service import SubscriptionService


class OfferEngine:
    """Offer selection (trial, first-time discount, comeback).

    Uses real history (events + subscription) and avoids spam.
    """

    def __init__(self, config: MonetizationConfig = DEFAULT_MONETIZATION_CONFIG):
        self._c = config
        self._subs = SubscriptionService()

    def pick_offer(self, db: Session, user_id: int) -> dict:
        plan = self._subs.get_active_plan(db, user_id)
        if plan != "free":
            return {"offer_type": "subscription", "label": "Active plan"}

        # If user previously started a purchase but didn’t complete => comeback offer.
        week_ago = datetime.now(UTC) - timedelta(days=7)
        started = (
            db.query(AnalyticsEvent)
            .filter((AnalyticsEvent.user_id == user_id) & (AnalyticsEvent.name == "purchase_started") & (AnalyticsEvent.created_at >= week_ago))
            .count()
        )
        completed = (
            db.query(AnalyticsEvent)
            .filter((AnalyticsEvent.user_id == user_id) & (AnalyticsEvent.name == "purchase_completed") & (AnalyticsEvent.created_at >= week_ago))
            .count()
        )
        if started >= 1 and completed == 0:
            return {"offer_type": "comeback", "label": "Comeback offer", "discount_percent": self._c.first_time_discount_percent}

        # First time discount if they have ever seen a paywall and never purchased.
        ever_paywall = (
            db.query(AnalyticsEvent)
            .filter((AnalyticsEvent.user_id == user_id) & (AnalyticsEvent.name == "paywall_shown"))
            .count()
        )
        ever_purchase = (
            db.query(AnalyticsEvent)
            .filter((AnalyticsEvent.user_id == user_id) & (AnalyticsEvent.name == "purchase_completed"))
            .count()
        )
        if ever_paywall >= 1 and ever_purchase == 0:
            return {"offer_type": "discount", "label": "First-time discount", "discount_percent": self._c.first_time_discount_percent}

        return {"offer_type": "trial", "label": f"{self._c.trial_days}-day trial", "trial_days": self._c.trial_days}

