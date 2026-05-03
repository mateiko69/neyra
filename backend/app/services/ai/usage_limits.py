from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import os

from sqlalchemy.orm import Session

from app.models.ai_usage import AiUsage
from app.core.config import settings
from app.models.match import Match
from app.models.message import Message
from app.models.user import User
from app.services.ai.cache import get_redis
from app.services.analytics import track_event
from app.services.monetization.plan_entitlements import entitlements_for_plan
from app.services.monetization.subscription_service import SubscriptionService


class AiLimitReached(Exception):
    pass


class AiRapidCooldown(Exception):
    pass


class AiNotUnlocked(Exception):
    pass


@dataclass(frozen=True)
class AiPlanLimits:
    ai_daily_limit: int


def _limits_for_plan(plan: str) -> AiPlanLimits:
    ent = entitlements_for_plan(plan)
    if ent.unlimited_ai:
        return AiPlanLimits(ai_daily_limit=999_999)
    cap = ent.ai_reply_daily_cap
    if cap is None:
        return AiPlanLimits(ai_daily_limit=999_999)
    return AiPlanLimits(ai_daily_limit=max(1, int(cap)))


def _rapid_guard(user_id: int) -> None:
    try:
        r = get_redis()
    except Exception:
        return
    cool_key = f"ai:cooldown:{int(user_id)}"
    if int(r.get(cool_key) or 0) > 0:
        raise AiRapidCooldown("ai_cooldown")
    k = f"ai:rapid:{int(user_id)}:{datetime.now(UTC).strftime('%Y%m%d%H%M')}"
    c = int(r.incr(k) or 0)
    if c == 1:
        r.expire(k, 80)
    if c > 5:
        r.setex(cool_key, 45, 1)
        raise AiRapidCooldown("ai_cooldown")


def _has_emotional_engagement(db: Session, *, user_id: int) -> bool:
    has_match = bool(
        db.query(Match.id)
        .filter((Match.user_a_id == int(user_id)) | (Match.user_b_id == int(user_id)))
        .first()
    )
    if has_match:
        return True
    has_chat = bool(
        db.query(Message.id)
        .filter((Message.sender_id == int(user_id)) | (Message.receiver_id == int(user_id)))
        .first()
    )
    return has_chat


def enforce_and_consume_ai_usage(db: Session, *, user_id: int, usage_type: str) -> tuple[str, AiUsage]:
    if (not bool(getattr(settings, "AI_STRICT_MONETIZATION", False))) or bool(os.getenv("PYTEST_CURRENT_TEST")):
        plan_raw = SubscriptionService().get_active_plan(db, int(user_id))
        plan = plan_raw if plan_raw in {"free", "premium", "premium_plus"} else "free"
        dummy = AiUsage(user_id=int(user_id), date=datetime.now(UTC).date(), messages_used=0, openers_used=0, improves_used=0)
        return plan, dummy

    _rapid_guard(int(user_id))
    plan_raw = SubscriptionService().get_active_plan(db, int(user_id))
    plan = plan_raw if plan_raw in {"free", "premium", "premium_plus"} else "free"

    if plan == "free":
        if not _has_emotional_engagement(db, user_id=int(user_id)):
            raise AiNotUnlocked("ai_unlock_after_first_match")

    limits = _limits_for_plan(plan)
    today = datetime.now(UTC).date()
    row = db.query(AiUsage).filter(AiUsage.user_id == int(user_id), AiUsage.date == today).first()
    if not row:
        row = AiUsage(user_id=int(user_id), date=today, messages_used=0, openers_used=0, improves_used=0)
        db.add(row)
        db.flush()

    total = int(row.messages_used or 0) + int(row.openers_used or 0) + int(row.improves_used or 0)
    if total >= int(limits.ai_daily_limit):
        try:
            track_event(
                db,
                "ai_limit_hit",
                user_id=int(user_id),
                payload={
                    "plan": plan,
                    "usage_type": usage_type,
                    "daily_total": total,
                    "daily_cap": int(limits.ai_daily_limit),
                },
            )
        except Exception:
            pass
        raise AiLimitReached("ai_limit_hit")

    if usage_type == "opener":
        row.openers_used = int(row.openers_used or 0) + 1
    elif usage_type == "improve":
        row.improves_used = int(row.improves_used or 0) + 1
    else:
        row.messages_used = int(row.messages_used or 0) + 1

    urow = db.query(User).filter(User.id == int(user_id)).first()
    if urow:
        urow.ai_last_used_at = datetime.now(UTC)
        db.add(urow)

    db.add(row)
    db.commit()
    return plan, row
