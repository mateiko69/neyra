from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.models.device_token import DeviceToken
from app.models.match import Match
from app.models.message import Message
from app.models.user import User
from app.services.ai.cache import get_redis
from app.services.analytics import track_event
from app.services.notifications import send_user_notification
from app.services.retention.daily_boosts import get_daily_boosts_state
from app.services.retention.notification_engine import NotificationEngine

log = logging.getLogger("neyra.retention")


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _aware_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _eligible_user_ids(db: Session, limit: int = 800) -> list[int]:
    """
    Only consider users with device tokens (push-capable).
    Keep it cheap and bounded.
    """
    rows = (
        db.query(DeviceToken.user_id)
        .distinct()
        .limit(max(1, min(limit, 5000)))
        .all()
    )
    ids = [int(r[0]) for r in rows if r and r[0]]
    if not ids:
        return []
    users = (
        db.query(User)
        .filter(User.id.in_(ids))
        .all()
    )
    out: list[int] = []
    for u in users:
        if not u:
            continue
        if bool(getattr(u, "is_demo", False)):
            continue
        if bool(getattr(u, "is_deleted", False)) or bool(getattr(u, "is_banned", False)):
            continue
        out.append(int(u.id))
    return out[:limit]


def _count_new_matches_24h(db: Session, user_id: int, since: datetime) -> int:
    return int(
        db.query(Match)
        .filter(
            and_(
                or_(Match.user_a_id == int(user_id), Match.user_b_id == int(user_id)),
                Match.created_at >= since,
            )
        )
        .count()
        or 0
    )


def _count_profile_views_24h(db: Session, user_id: int, since: datetime) -> int:
    from app.models.analytics_event import AnalyticsEvent

    return int(
        db.query(AnalyticsEvent)
        .filter(
            and_(
                AnalyticsEvent.user_id == int(user_id),
                AnalyticsEvent.name == "profile_viewed",
                AnalyticsEvent.created_at >= since,
            )
        )
        .count()
        or 0
    )


def _has_dead_chat_24h(db: Session, user_id: int, threshold: datetime) -> bool:
    """
    Dead chat heuristic:
    - user received a message
    - last received message is >= 24h old
    - user has not sent anything after that timestamp
    """
    incoming = (
        db.query(Message)
        .filter(Message.receiver_id == int(user_id))
        .order_by(Message.created_at.desc())
        .first()
    )
    if not incoming or not getattr(incoming, "created_at", None):
        return False
    ts = incoming.created_at
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=UTC)
    if ts > threshold:
        return False
    sent_after = (
        db.query(Message)
        .filter(and_(Message.sender_id == int(user_id), Message.created_at > ts))
        .count()
    )
    return int(sent_after or 0) == 0


def run_retention_tick(db: Session) -> dict[str, int]:
    """
    Best-effort retention worker:
    - At most one **push** per user per tick (priority: revive > new matches > streak > profile views digest).
    - Micro-rewards are in-app only (no push) via NotificationEngine.
    """
    now = _utcnow()
    since_day = now - timedelta(days=1)
    dead_chat_threshold = now - timedelta(hours=24)

    engine = NotificationEngine()
    stats = {
        "users_considered": 0,
        "sent": 0,
        "suppressed": 0,
        "skipped_in_app_only": 0,
        "errors": 0,
        "daily_new_matches": 0,
        "daily_profile_views": 0,
        "dead_chat_revive": 0,
        "streak_reminder": 0,
        "device_token_rows": 0,
        "eligible_push_users": 0,
    }

    try:
        stats["device_token_rows"] = int(db.execute(select(func.count()).select_from(DeviceToken)).scalar() or 0)
    except Exception:
        stats["device_token_rows"] = 0

    eligible = _eligible_user_ids(db)
    stats["eligible_push_users"] = len(eligible)
    log.info(
        "retention_tick_candidates",
        extra={
            "device_token_rows": stats["device_token_rows"],
            "eligible_users": stats["eligible_push_users"],
        },
    )

    for uid in eligible:
        stats["users_considered"] += 1
        try:
            matches_24h = _count_new_matches_24h(db, uid, since_day)
            views_24h = _count_profile_views_24h(db, uid, since_day)
            has_dead_chat = _has_dead_chat_24h(db, uid, dead_chat_threshold)

            user_row = db.query(User).filter(User.id == int(uid)).first()
            boost = get_daily_boosts_state(db, user_id=uid)
            streak_days = int((boost or {}).get("streak_days") or 0)
            last_active = getattr(user_row, "last_active_at", None) if user_row else None
            streak_inactive = False
            if last_active and streak_days >= 3:
                la = _aware_utc(last_active)
                streak_inactive = la <= now - timedelta(hours=12)

            candidates: list[tuple[dict, int, str]] = []
            if has_dead_chat:
                candidates.append(({"type": "dead_chat_revive"}, 100, "dead_chat_revive"))
            if matches_24h > 0:
                candidates.append(({"type": "daily_new_matches", "count": matches_24h}, 90, "daily_new_matches"))
            if streak_inactive:
                candidates.append(({"type": "streak_reminder"}, 85, "streak_reminder"))
            if views_24h > 0:
                candidates.append(({"type": "daily_profile_views", "count": views_24h}, 50, "daily_profile_views"))

            candidates.sort(key=lambda x: -x[1])

            pushed = False
            for event, _prio, stat_key in candidates:
                decision = engine.decide_notification(db, uid, event)
                if not decision.send:
                    stats["suppressed"] += 1
                    continue
                if decision.channel != "push":
                    stats["skipped_in_app_only"] += 1
                    continue
                body = decision.body if (decision.body or "").strip() else " "
                send_user_notification(db, uid, decision.title, body)
                track_event(db, "notification_sent", user_id=uid, payload={"event": event, "decision": decision.to_dict()})
                stats["sent"] += 1
                if stat_key == "daily_new_matches":
                    stats["daily_new_matches"] += 1
                elif stat_key == "daily_profile_views":
                    stats["daily_profile_views"] += 1
                elif stat_key == "dead_chat_revive":
                    stats["dead_chat_revive"] += 1
                elif stat_key == "streak_reminder":
                    stats["streak_reminder"] += 1
                pushed = True
                break

            if not pushed and not candidates:
                pass

        except Exception:
            stats["errors"] += 1

    try:
        r = get_redis()
        if r:
            r.set("retention:last_tick_stats", json.dumps(stats), ex=86400)
    except Exception:
        pass

    return stats
