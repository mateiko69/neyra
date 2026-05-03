from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.domain.monetization.config import DEFAULT_MONETIZATION_CONFIG, MonetizationConfig
from app.domain.monetization.types import PaywallDecision
from app.models.analytics_event import AnalyticsEvent
from app.services.monetization.access import MonetizationAccess
from app.services.monetization.dynamic_paywall import (
    ALLOWED_DYNAMIC_TRIGGERS,
    apply_pricing_ladder,
    benefits_for_segment,
    compute_segment,
    headline_for_segment,
    normalize_trigger,
    paywall_shown_count,
    validate_trigger,
)
from app.services.monetization.offers import OfferEngine


class PaywallTrigger:
    """Contextual paywalls with UX rules:
    - never block messaging
    - never spam (cooldown)
    - always show value first
    """

    def __init__(self, config: MonetizationConfig = DEFAULT_MONETIZATION_CONFIG):
        self._c = config
        self._access = MonetizationAccess()
        self._offers = OfferEngine(config)

    def trigger_paywall(self, db: Session, user_id: int, context: dict) -> dict:
        ctype = (context.get("context") or context.get("type") or "").strip()
        stage = (context.get("stage") or "").strip().lower()

        # Cooldown guard (anti-spam)
        cooldown_since = datetime.now(UTC) - timedelta(hours=self._c.paywall_cooldown_hours)
        recently = (
            db.query(AnalyticsEvent)
            .filter((AnalyticsEvent.user_id == user_id) & (AnalyticsEvent.name == "paywall_shown") & (AnalyticsEvent.created_at >= cooldown_since))
            .count()
        )
        if recently >= 1:
            return PaywallDecision(False, "", "subscription").to_dict()

        offer = self._offers.pick_offer(db, user_id)

        if ctype == "first_match":
            msg = "Хочеш сильніші opener-и під стиль? Premium відкриває Wingman на максимум."
            return PaywallDecision(True, msg, offer["offer_type"]).to_dict()

        if ctype == "reply_suggestion_request":
            access = self._access.check_access(db, user_id, "ai_unlimited_replies")
            if access["allowed"]:
                return PaywallDecision(False, "", "subscription").to_dict()
            msg = "Хочеш більше варіантів відповіді й кращий тон? Відкрий безліміт AI replies."
            return PaywallDecision(True, msg, offer["offer_type"]).to_dict()

        if ctype == "conversation_dying":
            access = self._access.check_access(db, user_id, "ai_conversation_analysis")
            if access["allowed"]:
                return PaywallDecision(False, "", "subscription").to_dict()
            msg = "Діалог підсів? Premium дає коуч-інсайти й next-step підказки."
            return PaywallDecision(True, msg, offer["offer_type"]).to_dict()

        if ctype == "profile_boost_request":
            access = self._access.check_access(db, user_id, "profile_boost")
            if access["allowed"]:
                return PaywallDecision(False, "", "subscription").to_dict()
            msg = "Підсиль видимість профілю на 24 години — профільний Boost у Premium."
            return PaywallDecision(True, msg, offer["offer_type"]).to_dict()

        # Soft monetization: segment + offer ladder (never blocks core).
        if ctype in {"good_match", "chat_started", "engaged_user", "ai_suggestion_used"}:
            access = self._access.check_access(db, user_id, "ai_unlimited_replies")
            if access["allowed"]:
                return PaywallDecision(False, "", "subscription").to_dict()

            trigger = normalize_trigger(context, ctype)
            if trigger not in ALLOWED_DYNAMIC_TRIGGERS or not validate_trigger(db, user_id, trigger, ctype):
                return PaywallDecision(False, "", "subscription").to_dict()

            segment = compute_segment(db, user_id)
            idx = paywall_shown_count(db, user_id)
            offer_dyn = apply_pricing_ladder(offer, idx, segment, self._c)
            msg = headline_for_segment(segment)
            benefits = benefits_for_segment(segment)
            features = ["ai_unlimited_replies", "priority_visibility", "ai_match_boost"]
            out = PaywallDecision(True, msg, str(offer_dyn["offer_type"])).to_dict()
            out["benefits"] = benefits
            out["features"] = features
            out["context"] = ctype
            out["stage"] = stage or ("value_visible" if ctype in {"good_match", "chat_started"} else "engaged")
            out["segment"] = segment
            out["trigger"] = trigger
            out["paywall_index"] = idx
            if "discount_percent" in offer_dyn:
                out["discount_percent"] = offer_dyn["discount_percent"]
            if "trial_days" in offer_dyn:
                out["trial_days"] = offer_dyn["trial_days"]
            out["offer_type"] = offer_dyn["offer_type"]
            out["offer_label"] = offer_dyn.get("label")
            return out

        return PaywallDecision(False, "", "subscription").to_dict()

