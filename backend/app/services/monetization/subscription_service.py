from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.subscription import Subscription
from app.models.user import User
from app.services.monetization.plan_entitlements import normalize_internal_plan
from app.utils.datetime_utc import to_utc_aware


class SubscriptionService:
    """Subscription lookup: user mirror fields (Paddle) + legacy subscriptions row + periods."""

    @staticmethod
    def _effective_user_plan(user: User | None, now: datetime) -> str | None:
        if not user:
            return None
        plan = normalize_internal_plan(getattr(user, "subscription_plan", None))
        if plan not in {"premium", "premium_plus"}:
            return None
        st = str(getattr(user, "subscription_status", "") or "").strip().lower()
        exp = to_utc_aware(getattr(user, "subscription_expires_at", None))
        expired = False
        if exp is not None:
            try:
                expired = exp < now
            except Exception:
                expired = False
        if st in {"active", "past_due", "trialing"}:
            return None if expired else plan
        if st == "canceled":
            if exp is not None and not expired:
                return plan
            return None
        return None

    @staticmethod
    def _legacy_subscription_plan(row: Subscription | None, now: datetime) -> str | None:
        if not row:
            return None
        st = str(getattr(row, "status", "") or "").strip().lower()
        if st not in {"active", "past_due", "trialing"}:
            return None
        start = to_utc_aware(getattr(row, "start_date", None))
        end = to_utc_aware(getattr(row, "end_date", None))
        if start is not None and start > now:
            return None
        if end is not None and end < now:
            return None
        p = normalize_internal_plan(getattr(row, "plan_code", None))
        return p if p in {"premium", "premium_plus"} else None

    @staticmethod
    def _premium_trial_effective(user: User | None, now: datetime) -> bool:
        """True when signup/marketing trial window is active (no paid plan required)."""
        if not user:
            return False
        ta = to_utc_aware(getattr(user, "trial_expires_at", None))
        pu = to_utc_aware(getattr(user, "premium_until", None))
        end = ta or pu
        if end is None:
            return False
        try:
            return now < end
        except Exception:
            return False

    def get_billing_plan(self, db: Session, user_id: int) -> str:
        """Paid subscription tier only (mirror + legacy row). Does not infer signup trial."""
        try:
            if bool(getattr(settings, "DEV_FORCE_PREMIUM", False)) and str(getattr(settings, "ENV", "") or "").strip().lower() != "production":
                return "premium_plus"
        except Exception:
            pass
        now = datetime.now(UTC)
        user = db.query(User).filter(User.id == int(user_id)).first()
        mirrored = self._effective_user_plan(user, now)
        if mirrored:
            return mirrored

        row = db.query(Subscription).filter(Subscription.user_id == int(user_id)).first()
        legacy = self._legacy_subscription_plan(row, now)
        return legacy if legacy else "free"

    def get_active_plan(self, db: Session, user_id: int) -> str:
        """
        Effective UX tier: paid subscription OR active signup Premium trial → `premium`.
        """
        try:
            if bool(getattr(settings, "DEV_FORCE_PREMIUM", False)) and str(getattr(settings, "ENV", "") or "").strip().lower() != "production":
                return "premium_plus"
        except Exception:
            pass
        now = datetime.now(UTC)
        billing = self.get_billing_plan(db, int(user_id))
        if billing in {"premium", "premium_plus"}:
            return billing

        user = db.query(User).filter(User.id == int(user_id)).first()
        if user and self._premium_trial_effective(user, now):
            return "premium"

        return "free"
