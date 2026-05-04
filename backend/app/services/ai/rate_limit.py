from __future__ import annotations

from datetime import UTC, datetime
import logging

from app.core.config import settings
from app.services.ai.cache import get_redis
from app.services.monetization.plan_entitlements import entitlements_for_plan
from app.services.monetization.subscription_service import SubscriptionService
from app.services.retention.daily_boosts import get_daily_boosts_state, streak_extra_ai_day_budget
from sqlalchemy.orm import Session

logger = logging.getLogger("neyra.ratelimit")


class RateLimitExceeded(Exception):
    pass


def _day_key(user_id: int) -> str:
    day = datetime.now(UTC).strftime("%Y%m%d")
    return f"ai:rl:day:{day}:{user_id}"


def _min_key(user_id: int) -> str:
    minute = datetime.now(UTC).strftime("%Y%m%d%H%M")
    return f"ai:rl:min:{minute}:{user_id}"


def enforce_ai_limits(db: Session, user_id: int) -> None:
    """Enforce per-user limits using Redis counters (tier-aware)."""

    plan = SubscriptionService().get_active_plan(db, int(user_id))
    tier = plan if plan in {"free", "premium", "premium_plus"} else "free"
    ent = entitlements_for_plan(tier)
    minute_mult = 1
    if tier == "premium":
        minute_mult = 3
    elif tier == "premium_plus":
        minute_mult = 8

    per_min = max(1, int(settings.AI_CALLS_PER_MINUTE_FREE) * minute_mult)

    per_day = max(1, int(settings.AI_CALLS_PER_DAY_FREE))
    if ent.unlimited_ai:
        per_day = max(per_day * 250, int(settings.AI_CALLS_PER_DAY_PREMIUM) * 120)
    elif ent.ai_reply_daily_cap is not None:
        per_day = max(1, int(ent.ai_reply_daily_cap))
    else:
        if tier == "free":
            try:
                st = get_daily_boosts_state(db, user_id=int(user_id))
                per_day += streak_extra_ai_day_budget(int(st.get("streak_days") or 1))
            except Exception:
                pass
        else:
            per_day *= minute_mult

    if str(getattr(settings, "ENV", "") or "").strip().lower() == "development":
        per_min = max(per_min, 60 * minute_mult)
        per_day = max(per_day, 800 * minute_mult)

    try:
        r = get_redis()
    except Exception:
        return
    mk = _min_key(user_id)
    dk = _day_key(user_id)

    try:
        m = r.incr(mk)
        if m == 1:
            r.expire(mk, 90)
        d = r.incr(dk)
        if d == 1:
            r.expire(dk, 60 * 60 * 30)
    except Exception:
        logger.warning("enforce_ai_limits redis counters failed user_id=%s", int(user_id), exc_info=True)
        return

    logger.info(
        "rate_limit_tier_used",
        extra={"tier": tier, "scope": "ai", "per_min": per_min, "per_day": per_day, "minute_used": m, "day_used": d},
    )

    if m > per_min or d > per_day:
        raise RateLimitExceeded("ai_rate_limited")
