from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
import os

from sqlalchemy.exc import DBAPIError, OperationalError, ProgrammingError
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

logger = logging.getLogger(__name__)


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
    try:
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
    except AiRapidCooldown:
        raise
    except Exception:
        logger.warning("ai rapid_guard redis degraded user_id=%s", int(user_id), exc_info=True)
        return


def _has_emotional_engagement(db: Session, *, user_id: int) -> bool:
    try:
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
    except (OperationalError, ProgrammingError, DBAPIError):
        logger.warning("emotional_engagement_query_failed user_id=%s", int(user_id), exc_info=True)
        try:
            db.rollback()
        except Exception:
            pass
        return True
    except Exception:
        logger.warning("emotional_engagement_unexpected user_id=%s", int(user_id), exc_info=True)
        return True


def _dummy_ai_usage(user_id: int) -> AiUsage:
    return AiUsage(
        user_id=int(user_id),
        date=datetime.now(UTC).date(),
        messages_used=0,
        openers_used=0,
        improves_used=0,
    )


def _safe_active_plan(db: Session, user_id: int) -> str:
    try:
        plan_raw = SubscriptionService().get_active_plan(db, int(user_id))
        return plan_raw if plan_raw in {"free", "premium", "premium_plus"} else "free"
    except Exception:
        logger.warning("get_active_plan_failed user_id=%s", int(user_id), exc_info=True)
        return "free"


def enforce_and_consume_ai_usage(db: Session, *, user_id: int, usage_type: str) -> tuple[str, AiUsage]:
    if (not bool(getattr(settings, "AI_STRICT_MONETIZATION", False))) or bool(os.getenv("PYTEST_CURRENT_TEST")):
        plan = _safe_active_plan(db, int(user_id))
        return plan, _dummy_ai_usage(int(user_id))

    try:
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
    except (AiLimitReached, AiRapidCooldown, AiNotUnlocked):
        raise
    except (OperationalError, ProgrammingError, DBAPIError):
        logger.warning(
            "enforce_ai_usage_db_degraded user_id=%s usage_type=%s",
            int(user_id),
            usage_type,
            exc_info=True,
        )
        try:
            db.rollback()
        except Exception:
            pass
        return _safe_active_plan(db, int(user_id)), _dummy_ai_usage(int(user_id))
    except Exception:
        logger.warning(
            "enforce_ai_usage_unexpected user_id=%s usage_type=%s",
            int(user_id),
            usage_type,
            exc_info=True,
        )
        try:
            db.rollback()
        except Exception:
            pass
        return _safe_active_plan(db, int(user_id)), _dummy_ai_usage(int(user_id))
