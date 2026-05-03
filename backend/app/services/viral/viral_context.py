"""Product-embedded viral signals: social proof, visibility loop hints, profile highlight eligibility."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.message import Message
from app.models.profile import Profile
from app.models.user import User
from app.services.trust.profile_quality import compute_profile_quality

# Align with discover feed ranking (see endpoints/discover.py).
_ACTIVE_BOOST_MAX = 6.0


def _start_of_utc_day(now: datetime) -> datetime:
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def signups_today_count(db: Session) -> int:
    now = datetime.now(UTC)
    start = _start_of_utc_day(now)
    return int(
        db.query(func.count(User.id))
        .filter(User.created_at >= start, User.is_demo.is_(False), User.is_deleted.is_(False))
        .scalar()
        or 0
    )


def _activity_boost_points(db: Session, user_id: int) -> float:
    u = db.query(User).filter(User.id == int(user_id)).first()
    if not u:
        return 0.0
    ts = getattr(u, "last_active_at", None) or getattr(u, "created_at", None)
    if not ts:
        return 0.0
    if getattr(ts, "tzinfo", None) is None:
        ts = ts.replace(tzinfo=UTC)
    now = datetime.now(UTC)
    age_days = max(0.0, (now - ts).total_seconds() / (60 * 60 * 24))
    freshness = max(0.0, min(1.0, 1.0 - (age_days / 30.0)))
    base = float(_ACTIVE_BOOST_MAX) * freshness
    since = now - timedelta(days=7)
    sent = int(
        db.query(func.count(Message.id))
        .filter(
            Message.sender_id == int(user_id),
            Message.created_at >= since,
            Message.is_demo_simulation.is_(False),
        )
        .scalar()
        or 0
    )
    chatter = min(3.0, float(sent) * 0.35)
    return min(_ACTIVE_BOOST_MAX + 2.0, base + chatter)


def visibility_loop_tier(db: Session, user_id: int) -> dict:
    pts = _activity_boost_points(db, user_id)
    if pts >= 5.5:
        tier = "high"
    elif pts >= 2.5:
        tier = "medium"
    else:
        tier = "low"
    return {
        "tier": tier,
        "activity_points": round(pts, 2),
        "caption": "high" if tier == "high" else ("medium" if tier == "medium" else "low"),
    }


def profile_highlight_eligible(db: Session, user_id: int) -> dict:
    profile = db.query(Profile).filter(Profile.user_id == int(user_id)).first()
    if not profile:
        return {"eligible": False, "strength": "low"}
    q = compute_profile_quality(profile)
    since = datetime.now(UTC) - timedelta(days=7)
    sent = int(
        db.query(func.count(Message.id))
        .filter(Message.sender_id == int(user_id), Message.created_at >= since, Message.is_demo_simulation.is_(False))
        .scalar()
        or 0
    )
    ok = q.quality_flag == "ok"
    eligible = ok and (sent >= 1 or _activity_boost_points(db, user_id) >= 3.0)
    strength = "high" if ok and sent >= 5 else ("medium" if eligible else "low")
    return {"eligible": bool(eligible), "strength": strength, "quality_ok": ok}


def get_viral_context(db: Session, user_id: int) -> dict:
    n = signups_today_count(db)
    band = min(500, max(0, n))
    vis = visibility_loop_tier(db, user_id)
    ph = profile_highlight_eligible(db, user_id)
    return {
        "social_proof": {
            "joining_today_count": band,
            "show_banner": band >= 3,
        },
        "visibility_loop": vis,
        "profile_highlight": ph,
    }
