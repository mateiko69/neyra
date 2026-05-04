import logging
from dataclasses import asdict
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.api_errors import api_error
from app.api.deps import get_db, get_current_user
from app.core.config import settings
from app.models.ai_usage import AiUsage
from app.models.subscription import Subscription
from app.models.user import User
from app.services.monetization.plan_entitlements import entitlements_for_plan
from app.services.monetization.subscription_service import SubscriptionService
from app.services.monetization.subscription_sync import apply_subscription_mirror
from app.services.payments.service import get_payments_provider

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/checkout")
def create_checkout(payload: dict, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    plan_code = str(payload.get("plan_code", "premium") or "premium").strip().lower()
    if plan_code not in {"premium", "premium_plus"}:
        raise HTTPException(status_code=400, detail=api_error("subscription.invalid_plan"))
    provider = get_payments_provider()
    checkout = provider.create_checkout_session(current_user.id, plan_code)

    # Mock provider: simulate an immediate successful upgrade in dev/test.
    if str(settings.PAYMENTS_PROVIDER or "").strip().lower() == "mock":
        until = datetime.now(UTC) + timedelta(days=30)
        apply_subscription_mirror(
            db,
            user_id=int(current_user.id),
            internal_plan=plan_code,
            status="active",
            expires_at=until,
            provider="mock",
            provider_customer_id=f"mock_user_{int(current_user.id)}",
            provider_subscription_id=f"mock_sub_{int(current_user.id)}",
            start_date=datetime.now(UTC),
        )
        row = db.query(Subscription).filter(Subscription.user_id == current_user.id).first()
        return {
            **(checkout or {}),
            "activated": True,
            "plan_code": row.plan_code if row else plan_code,
            "status": row.status if row else "active",
        }

    return checkout


def _ent_dict(plan: str) -> dict:
    ent = entitlements_for_plan(plan)
    d = asdict(ent)
    return d


def _ai_usage_today(db: Session, *, user_id: int, plan: str) -> dict:
    ent = entitlements_for_plan(plan)
    today = datetime.now(UTC).date()
    row = db.query(AiUsage).filter(AiUsage.user_id == int(user_id), AiUsage.date == today).first()
    used = 0
    if row:
        used = int(row.messages_used or 0) + int(row.openers_used or 0) + int(row.improves_used or 0)
    limit: int | None = None
    if not ent.unlimited_ai and ent.ai_reply_daily_cap is not None:
        limit = int(ent.ai_reply_daily_cap)
    return {"used": used, "limit": limit, "unlimited": bool(ent.unlimited_ai)}


def _ai_usage_today_safe(db: Session, *, user_id: int, plan: str) -> dict:
    try:
        return _ai_usage_today(db, user_id=user_id, plan=plan)
    except Exception:
        logger.warning("ai_usage_today failed user_id=%s", user_id, exc_info=True)
        ent = entitlements_for_plan(plan)
        limit: int | None = None
        if not ent.unlimited_ai and ent.ai_reply_daily_cap is not None:
            limit = int(ent.ai_reply_daily_cap)
        return {"used": 0, "limit": limit, "unlimited": bool(ent.unlimited_ai)}


def _subscription_expires_iso(exp: object | None) -> str | None:
    if exp is None:
        return None
    try:
        iso = getattr(exp, "isoformat", None)
        if callable(iso):
            return str(iso())
    except Exception:
        return None
    return None


def _subscription_me_safe_payload() -> dict:
    plan = "free"
    return {
        "status": "inactive",
        "plan_code": plan,
        "billing_plan": plan,
        "provider": str(getattr(settings, "PAYMENTS_PROVIDER", None) or "mock"),
        "subscription_expires_at": None,
        "entitlements": _ent_dict(plan),
        "trial_active": False,
        "trial_expires_at": None,
        "ai_usage_today": {"used": 0, "limit": 8, "unlimited": False},
    }


def _build_my_subscription(current_user: User, db: Session) -> dict:
    try:
        try:
            if bool(getattr(settings, "DEV_FORCE_PREMIUM", False)) and str(getattr(settings, "ENV", "") or "").strip().lower() != "production":
                return {
                    "status": "active",
                    "plan_code": "premium_plus",
                    "billing_plan": "premium_plus",
                    "provider": "dev_override",
                    "subscription_expires_at": None,
                    "entitlements": _ent_dict("premium_plus"),
                    "trial_active": False,
                    "trial_expires_at": None,
                    "ai_usage_today": {"used": 0, "limit": None, "unlimited": True},
                }
        except Exception:
            pass
        subs = SubscriptionService()
        billing_plan = subs.get_billing_plan(db, int(current_user.id))
        plan = subs.get_active_plan(db, int(current_user.id))
        u = db.query(User).filter(User.id == int(current_user.id)).first()
        now = datetime.now(UTC)
        row = db.query(Subscription).filter(Subscription.user_id == current_user.id).first()
        prov = (row.provider if row and row.provider else None) or str(settings.PAYMENTS_PROVIDER or "mock")
        exp = getattr(u, "subscription_expires_at", None) if u else None

        trial_active_flag = billing_plan == "free" and plan == "premium"
        trial_expires_iso = None
        try:
            if trial_active_flag and u:
                te = getattr(u, "trial_expires_at", None)
                pu = getattr(u, "premium_until", None)
                ta = te if te else pu
                if ta is not None:
                    if getattr(ta, "tzinfo", None) is None:
                        ta = ta.replace(tzinfo=UTC)
                    if now < ta:
                        trial_expires_iso = ta.isoformat()
                    else:
                        trial_active_flag = False
        except Exception:
            trial_expires_iso = None
            trial_active_flag = False

        if billing_plan in {"premium", "premium_plus"}:
            st = str(getattr(u, "subscription_status", "") or "active") if u else "active"
            if st not in {"active", "past_due", "canceled"} and row and row.status:
                st = str(row.status)
            status_out = st
        elif trial_active_flag:
            status_out = "trialing"
        else:
            status_out = "inactive"

        return {
            "status": status_out,
            "plan_code": plan,
            "billing_plan": billing_plan,
            "provider": prov,
            "subscription_expires_at": _subscription_expires_iso(exp),
            "entitlements": _ent_dict(plan),
            "trial_active": trial_active_flag,
            "trial_expires_at": trial_expires_iso,
            "ai_usage_today": _ai_usage_today_safe(db, user_id=int(current_user.id), plan=plan),
        }
    except Exception:
        logger.exception("subscriptions_me_failed user_id=%s", getattr(current_user, "id", None))
        return _subscription_me_safe_payload()


@router.get("/me")
def my_subscription(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _build_my_subscription(current_user, db)
