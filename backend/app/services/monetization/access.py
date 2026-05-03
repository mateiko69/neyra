from __future__ import annotations

from sqlalchemy.orm import Session

from app.domain.monetization.types import AccessResult, PremiumFeature
from app.services.monetization.subscription_service import SubscriptionService


FEATURE_MIN_PLAN: dict[str, str] = {
    "ai_unlimited_replies": "premium_plus",
    "ai_conversation_analysis": "premium",
    # Full "who liked you" grid is Premium+ (Premium tier gets limited AI + visibility boost).
    "see_who_liked_you": "premium_plus",
    "profile_boost": "premium",
    "advanced_match_insights": "premium",
    # Premium+ upsell: surface best likes first (not required to view).
    "likes_priority_high_match": "premium_plus",
    "ai_timing_decision": "premium_plus",
    "meeting_readiness": "premium",
    "chat_revive_advanced": "premium_plus",
    "priority_in_discover": "premium_plus",
    "can_reopen_chat": "premium",
}


class MonetizationAccess:
    """Feature gating that never blocks core messaging."""

    def __init__(self):
        self._subs = SubscriptionService()

    def check_access(self, db: Session, user_id: int, feature: PremiumFeature) -> dict:
        plan = self._subs.get_active_plan(db, user_id)
        required = FEATURE_MIN_PLAN.get(feature, "free")
        if required == "free":
            return AccessResult(True, "free", False).to_dict()

        order = {"free": 0, "premium": 1, "premium_plus": 2}
        if order.get(plan, 0) >= order.get(required, 0):
            return AccessResult(True, "active_subscription", False).to_dict()

        return AccessResult(False, "upgrade_required", True).to_dict()

