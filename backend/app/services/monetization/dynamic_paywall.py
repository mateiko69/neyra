from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.domain.monetization.config import MonetizationConfig
from app.models.analytics_event import AnalyticsEvent
from app.models.message import Message

WINDOW_DAYS = 7
AI_VALIDATION_MINUTES = 8

ALLOWED_DYNAMIC_TRIGGERS = frozenset({"good_match", "engaged_user", "ai_suggestion_used", "chat_milestone"})


def _since(days: int) -> datetime:
    return datetime.now(UTC) - timedelta(days=days)


def _event_count(db: Session, user_id: int, names: tuple[str, ...], days: int) -> int:
    since = _since(days)
    return int(
        db.query(func.count(AnalyticsEvent.id))
        .filter(
            AnalyticsEvent.user_id == user_id,
            AnalyticsEvent.name.in_(names),
            AnalyticsEvent.created_at >= since,
        )
        .scalar()
        or 0
    )


def _message_stats(db: Session, user_id: int, days: int) -> tuple[int, int]:
    since = _since(days)
    sent = int(
        db.query(func.count(Message.id))
        .filter(
            Message.sender_id == user_id,
            Message.created_at >= since,
            Message.is_demo_simulation.is_(False),
        )
        .scalar()
        or 0
    )
    distinct = int(
        db.query(func.count(func.distinct(Message.receiver_id)))
        .filter(
            Message.sender_id == user_id,
            Message.created_at >= since,
            Message.is_demo_simulation.is_(False),
        )
        .scalar()
        or 0
    )
    return sent, distinct


def paywall_shown_count(db: Session, user_id: int) -> int:
    return int(
        db.query(func.count(AnalyticsEvent.id))
        .filter(AnalyticsEvent.user_id == user_id, AnalyticsEvent.name == "paywall_shown")
        .scalar()
        or 0
    )


def compute_segment(db: Session, user_id: int) -> str:
    sent, distinct = _message_stats(db, user_id, WINDOW_DAYS)
    msg_events = _event_count(db, user_id, ("message_sent",), WINDOW_DAYS)
    discover_views = _event_count(db, user_id, ("discover_card_viewed",), WINDOW_DAYS)
    profile_views = _event_count(db, user_id, ("profile_viewed",), WINDOW_DAYS)
    ai_touch = _event_count(
        db,
        user_id,
        ("ai_suggestion_sent", "first_message_ai_assisted", "ai_copilot_sent_after_use"),
        WINDOW_DAYS,
    )
    browse = discover_views + profile_views

    if sent >= 8 or msg_events >= 10 or (sent >= 4 and distinct >= 3) or ai_touch >= 5:
        return "high"
    if browse >= 8 and sent <= 6 and distinct <= 2:
        return "medium"
    if 1 <= sent <= 6 and browse >= 4:
        return "medium"
    return "low"


def headline_for_segment(segment: str) -> str:
    if segment == "high":
        return "Unlock better replies"
    if segment == "medium":
        return "Get more matches"
    return "Try premium free for 1 day"


def benefits_for_segment(segment: str) -> list[str]:
    if segment == "high":
        return [
            "Stronger AI rewrites tailored to your tone",
            "Unlimited reply ideas when chats heat up",
            "Priority when compatibility is high",
        ]
    if segment == "medium":
        return [
            "More visibility in discover",
            "Smarter openers when you swipe",
            "Match boost when you are ready to write",
        ]
    return [
        "Full premium for 1 day — no friction",
        "Try unlimited AI before you commit",
        "Cancel anytime if it is not for you",
    ]


def normalize_trigger(context: dict, ctype: str) -> str:
    raw = (context.get("trigger") or "").strip().lower()
    if raw in ALLOWED_DYNAMIC_TRIGGERS:
        return raw
    c = ctype.strip().lower()
    if c == "good_match":
        return "good_match"
    if c == "engaged_user":
        return "engaged_user"
    if c in {"chat_started", "chat_milestone"}:
        return "chat_milestone"
    if c in {"ai_suggestion_used", "reply_suggestion_request"}:
        return "ai_suggestion_used"
    return ""


def validate_trigger(db: Session, user_id: int, trigger: str, ctype: str) -> bool:
    if trigger == "good_match":
        return ctype.strip().lower() in {"good_match", "first_match"}

    if trigger == "engaged_user":
        if ctype.strip().lower() != "engaged_user":
            return False
        if _event_count(db, user_id, ("first_reply_received",), 3) >= 1:
            return True
        since = datetime.now(UTC) - timedelta(hours=2)
        got_reply = int(
            db.query(func.count(Message.id))
            .filter(Message.receiver_id == user_id, Message.created_at >= since, Message.is_demo_simulation.is_(False))
            .scalar()
            or 0
        )
        return got_reply >= 1

    if trigger == "ai_suggestion_used":
        if _event_count(db, user_id, ("ai_suggestion_sent", "first_message_ai_assisted", "ai_copilot_sent_after_use"), 14) >= 1:
            return True
        since = datetime.now(UTC) - timedelta(minutes=AI_VALIDATION_MINUTES)
        recent = (
            db.query(func.count(Message.id))
            .filter(
                Message.sender_id == user_id,
                Message.created_at >= since,
                Message.is_demo_simulation.is_(False),
            )
            .scalar()
            or 0
        )
        return int(recent) >= 1

    if trigger == "chat_milestone":
        sent, distinct = _message_stats(db, user_id, 14)
        return distinct >= 2 or sent >= 6

    return False


def apply_pricing_ladder(offer: dict, paywall_index: int, segment: str, config: MonetizationConfig) -> dict:
    out = dict(offer)
    base_discount = int(out.get("discount_percent") or config.first_time_discount_percent)
    base_trial = int(out.get("trial_days") or config.trial_days)

    if paywall_index <= 0:
        out["discount_percent"] = min(50, base_discount + 10)
        if out.get("offer_type") == "trial":
            out["trial_days"] = max(3, base_trial)
            if segment == "low":
                out["trial_days"] = 1
    elif paywall_index == 1:
        out["discount_percent"] = base_discount
        if "trial_days" in out or out.get("offer_type") == "trial":
            out["trial_days"] = base_trial
    else:
        out["discount_percent"] = max(12, base_discount - 12)
        if "trial_days" in out or out.get("offer_type") == "trial":
            out["trial_days"] = max(1, min(base_trial, 2))

    return out
