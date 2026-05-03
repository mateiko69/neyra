"""Single source of truth for daily boost + streak state (UserAiMemory daily/boosts)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.models.user_ai_memory import UserAiMemory

# Free tier: smart inline reply generations (timed-replies "now") per UTC day.
FREE_TIER_AI_REPLY_SLOTS_PER_DAY = 3


def _today_utc() -> str:
    return datetime.now(UTC).date().isoformat()


def today_utc_iso() -> str:
    return _today_utc()


def _yesterday_utc() -> str:
    return (datetime.now(UTC).date() - timedelta(days=1)).isoformat()


def _load_row(db: Session, user_id: int) -> UserAiMemory | None:
    return (
        db.query(UserAiMemory)
        .filter(UserAiMemory.user_id == int(user_id), UserAiMemory.memory_type == "daily", UserAiMemory.key == "boosts")
        .first()
    )


def _reset_state_for_day(prev: dict | None) -> dict:
    today = _today_utc()
    last_active = str((prev or {}).get("last_active_day") or "").strip()
    streak = int((prev or {}).get("streak_days") or 0)
    if last_active == _yesterday_utc():
        streak = max(1, min(365, streak + 1))
    else:
        streak = 1
    return {
        "day": today,
        "last_active_day": today,
        "streak_days": streak,
        "opener_used": False,
        "reply_used": False,
        "reply_uses": 0,
        "reveal_used": False,
        "revive_used": False,
        "meeting_used": False,
        "curiosity_like_shown": False,
        "banner_dismissed": False,
    }


def _merge_missing(value: dict) -> dict:
    """Backward compat for rows created before meeting_used / reply_used."""
    defaults = {
        "meeting_used": False,
        "reply_used": False,
        "reply_uses": 0,
        "reveal_used": False,
        "revive_used": False,
        "opener_used": False,
        "curiosity_like_shown": False,
        "banner_dismissed": False,
    }
    raw = dict(value or {})
    out = dict(raw)
    for k, v in defaults.items():
        out.setdefault(k, v)
    if "reply_uses" not in raw and bool(out.get("reply_used")):
        out["reply_uses"] = int(FREE_TIER_AI_REPLY_SLOTS_PER_DAY)
    return out


def get_daily_boosts_state(db: Session, *, user_id: int) -> dict:
    row = _load_row(db, user_id)
    now = datetime.now(UTC)
    if not row:
        row = UserAiMemory(
            user_id=int(user_id),
            memory_type="daily",
            key="boosts",
            value_json=_reset_state_for_day(None),
            confidence_score=0.5,
            source="system",
            created_at=now,
            updated_at=now,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return _merge_missing(dict(row.value_json or {}))

    value = _merge_missing(dict(row.value_json or {}))
    if str(value.get("day") or "").strip() != _today_utc():
        value = _reset_state_for_day(value)
        row.value_json = value
        row.updated_at = now
        db.add(row)
        db.commit()
        db.refresh(row)
        return _merge_missing(dict(row.value_json or {}))

    if str(value.get("last_active_day") or "").strip() != _today_utc():
        value["last_active_day"] = _today_utc()
        row.value_json = value
        row.updated_at = now
        db.add(row)
        db.commit()
        db.refresh(row)
    return _merge_missing(dict(row.value_json or {}))


def save_daily_boosts_state(db: Session, *, user_id: int, value: dict) -> dict:
    row = _load_row(db, user_id)
    now = datetime.now(UTC)
    merged = _merge_missing(dict(value))
    if not row:
        row = UserAiMemory(
            user_id=int(user_id),
            memory_type="daily",
            key="boosts",
            value_json=merged,
            confidence_score=0.5,
            source="system",
            created_at=now,
            updated_at=now,
        )
    else:
        row.value_json = merged
        row.updated_at = now
    db.add(row)
    db.commit()
    db.refresh(row)
    return _merge_missing(dict(row.value_json or {}))


def consume_daily_boost_slot(db: Session, *, user_id: int, boost_type: str) -> None:
    """Mark a daily slot used (opener|reply|reveal|revive|meeting)."""
    bt = str(boost_type or "").strip().lower()
    if bt not in {"opener", "reply", "reveal", "revive", "meeting"}:
        return
    st = get_daily_boosts_state(db, user_id=int(user_id))
    if bt == "reply":
        u = int(st.get("reply_uses") or 0)
        st["reply_uses"] = min(int(FREE_TIER_AI_REPLY_SLOTS_PER_DAY), u + 1)
        st["reply_used"] = bool(int(st["reply_uses"]) >= int(FREE_TIER_AI_REPLY_SLOTS_PER_DAY))
    else:
        st[f"{bt}_used"] = True
    save_daily_boosts_state(db, user_id=int(user_id), value=st)


def streak_bonus_ai_chat_fetches(streak_days: int) -> int:
    """Extra free-tier chat-brain fetches per day from streak (client + server hints)."""
    s = max(0, int(streak_days or 0))
    if s < 2:
        return 0
    return min(3, 1 + (s - 2) // 3)


def streak_extra_ai_day_budget(streak_days: int) -> int:
    """Extra AI calls allowed per UTC day on free tier (Redis rate limit)."""
    s = max(0, int(streak_days or 0))
    return min(18, max(0, (s - 1) * 2))
