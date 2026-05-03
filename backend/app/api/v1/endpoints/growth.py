from datetime import UTC, datetime

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_current_user
from app.models.user import User
from app.services.analytics import track_event
from app.services.premium_trial import maybe_start_premium_trial

from app.application.use_cases.growth.engagement import calculate_engagement_state
from app.application.use_cases.growth.nudges import generate_nudges
from app.application.use_cases.growth.notifications import decide_notification
from app.application.use_cases.monetization.check_access import check_access
from app.application.use_cases.monetization.trigger_paywall import trigger_paywall
from app.application.use_cases.growth.referral import generate_referral
from app.services.viral.viral_context import get_viral_context
from app.services.monetization.subscription_service import SubscriptionService
from app.api.api_errors import api_error
from app.services.monetization.boosts import activate_boost
from app.services.ai.cache import get_redis
from app.services.monetization.plan_entitlements import entitlements_for_plan


router = APIRouter()


@router.post("/engagement")
def growth_engagement(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    state = calculate_engagement_state(db, current_user.id)
    track_event(db, "user_returned", user_id=current_user.id, payload=state)
    try:
        from app.services.monetization.subscription_service import SubscriptionService

        if SubscriptionService().get_active_plan(db, current_user.id) != "free":
            track_event(db, "premium_subscriber_engagement", user_id=current_user.id, payload=state)
    except Exception:
        pass
    return state


@router.post("/nudges")
def growth_nudges(payload: dict = Body(default={}), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    # If engagement state not provided, compute.
    state = payload.get("engagement_state")
    if not state:
        state = calculate_engagement_state(db, current_user.id)
    nudges = generate_nudges(db, current_user.id, state)
    if nudges:
        track_event(db, "nudge_shown", user_id=current_user.id, payload={"count": len(nudges)})
    return {"nudges": nudges, "engagement_state": state}


@router.post("/notifications")
def growth_notifications(payload: dict = Body(...), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    event = payload.get("event") or {}
    decision = decide_notification(db, current_user.id, event)
    if decision.get("send"):
        track_event(db, "notification_sent", user_id=current_user.id, payload={"event": event, "decision": decision})
    return decision


@router.post("/premium/check")
def growth_premium_check(payload: dict = Body(...), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    feature = str(payload.get("feature", "")).strip()
    if not feature:
        raise HTTPException(status_code=400, detail="feature is required")
    return check_access(db, current_user.id, feature)


@router.post("/trial/activate")
def activate_trial(payload: dict = Body(default={}), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Conversion-optimized premium trial activation (one-time)."""
    reason = str(payload.get("reason") or "").strip() or "unknown"
    # Allowlist reasons to prevent abuse / noisy analytics.
    if reason not in {"ai_suggestion_clicked", "sent_3_messages"}:
        reason = "unknown"
    started = False
    try:
        started = maybe_start_premium_trial(db, user_id=int(current_user.id), reason=reason)
    except Exception:
        started = False
    track_event(db, "trial_activate_called", user_id=current_user.id, payload={"reason": reason, "started": bool(started)})
    return {"started": bool(started)}


@router.post("/paywall")
def growth_paywall(payload: dict = Body(default={}), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    decision = trigger_paywall(db, current_user.id, payload)
    if decision.get("show"):
        track_event(db, "paywall_shown", user_id=current_user.id, payload=decision)
    return decision


@router.post("/referral")
def growth_referral(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    res = generate_referral(db, current_user.id)
    return res


@router.get("/viral-context")
def growth_viral_context(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Social proof, visibility loop, and share eligibility for in-product viral surfaces."""
    return get_viral_context(db, int(current_user.id))


@router.post("/ab/resolve")
def growth_ab_resolve(payload: dict = Body(default={}), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Return A/B copy variants for UI keys; records at most one ab_exposure per assignment."""
    from app.services.ab_engine import EXPERIMENT_KEYS, resolve_copy

    keys = payload.get("keys")
    if not isinstance(keys, list) or not keys:
        keys = list(EXPERIMENT_KEYS)
    keys = [str(k).strip() for k in keys if str(k).strip() in EXPERIMENT_KEYS]
    if not keys:
        keys = list(EXPERIMENT_KEYS)
    record = payload.get("record_exposure", True)
    if not isinstance(record, bool):
        record = True
    return resolve_copy(db, user_id=int(current_user.id), keys=keys, record_exposure=record)


@router.post("/ab/event")
def growth_ab_event(payload: dict = Body(default={}), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Track A/B metrics: click | message_sent | reply | premium."""
    from app.services.ab_engine import record_metric

    extra = payload.get("extra")
    record_metric(
        db,
        user_id=int(current_user.id),
        experiment_key=str(payload.get("experiment_key") or ""),
        variant_id=str(payload.get("variant_id") or ""),
        metric=str(payload.get("metric") or ""),
        extra=extra if isinstance(extra, dict) else None,
    )
    return {"ok": True}


@router.post("/boost/activate")
def activate_profile_boost(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """
    Premium perk: boosts your visibility for a short window.
    Stored in Redis so it stays lightweight (best-effort).
    """
    plan = "free"
    try:
        plan = SubscriptionService().get_active_plan(db, int(current_user.id))
    except Exception:
        plan = "free"
    if plan not in {"premium", "premium_plus"}:
        raise HTTPException(status_code=402, detail=api_error("paywall.boost_requires_premium"))

    ent = entitlements_for_plan(plan)
    allow = max(0, int(ent.daily_boost_allowance or 0))
    if allow > 0:
        try:
            r = get_redis()
            day = datetime.now(UTC).strftime("%Y%m%d")
            k = f"growth:boost:quota:{day}:{int(current_user.id)}"
            used = int(r.incr(k))
            if used == 1:
                r.expire(k, 86400 * 3)
            if used > allow:
                raise HTTPException(status_code=402, detail=api_error("paywall.boost_daily_quota", limit=allow))
        except HTTPException:
            raise
        except Exception:
            # Redis optional: skip quota enforcement if unavailable.
            pass

    ok = activate_boost(int(current_user.id))
    track_event(db, "boost_activated", user_id=current_user.id, payload={"stored": bool(ok), "plan": plan})
    return {"ok": True, "stored": bool(ok)}

