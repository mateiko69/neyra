"""Referral milestones: count valid invitees, grant premium once per milestone, abuse heuristics."""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.models.analytics_event import AnalyticsEvent
from app.models.referral_reward_grant import ReferralRewardGrant
from app.models.user import User

MILESTONES: tuple[tuple[int, int, str, str], ...] = (
    (1, 3, "refs_1", "3 days Premium"),
    (3, 7, "refs_3", "7 days Premium"),
    (10, 30, "refs_10", "30 days Premium"),
)


def referral_identity_fingerprint(email: str | None) -> str:
    """Best-effort dedupe for referral counting (e.g. Gmail +aliases). Not a security boundary."""
    if not email:
        return ""
    raw = str(email).strip().lower()
    if "@" not in raw:
        return raw
    local, _, domain = raw.partition("@")
    domain = domain.lower()
    if domain in {"gmail.com", "googlemail.com"}:
        local = local.split("+", 1)[0]
        local = local.replace(".", "")
    return f"{local}@{domain}"


def _extend_premium_until(db: Session, user: User, days: int) -> None:
    now = datetime.now(UTC)
    current = getattr(user, "premium_until", None)
    if current is None:
        base = now
    else:
        cur = current
        if getattr(cur, "tzinfo", None) is None:
            cur = cur.replace(tzinfo=UTC)
        base = cur if cur > now else now
    user.premium_until = base + timedelta(days=int(days))
    db.add(user)


def _valid_referred_users_query(db: Session, inviter_id: int):
    return (
        db.query(User)
        .filter(
            User.referred_by_user_id == inviter_id,
            User.id != inviter_id,
            User.is_demo == False,  # noqa: E712
            User.is_banned == False,  # noqa: E712
            User.is_deleted == False,  # noqa: E712
        )
        .order_by(User.created_at.asc())
    )


def count_valid_referrals(db: Session, inviter_id: int) -> int:
    seen: set[str] = set()
    n = 0
    for u in _valid_referred_users_query(db, inviter_id).all():
        fp = referral_identity_fingerprint(getattr(u, "email", None)) or f"user:{u.id}"
        if fp in seen:
            continue
        seen.add(fp)
        n += 1
    return n


def list_earned_reward_rows(db: Session, user_id: int) -> list[ReferralRewardGrant]:
    return (
        db.query(ReferralRewardGrant)
        .filter(ReferralRewardGrant.user_id == int(user_id))
        .order_by(ReferralRewardGrant.created_at.asc())
        .all()
    )


def granted_milestone_keys(db: Session, user_id: int) -> set[str]:
    rows = db.query(ReferralRewardGrant.milestone_key).filter(ReferralRewardGrant.user_id == int(user_id)).all()
    return {str(r[0]) for r in rows if r and r[0]}


def next_reward_payload(valid_count: int, granted_keys: set[str]) -> dict | None:
    for threshold, _days, key, label in MILESTONES:
        if key in granted_keys:
            continue
        return {
            "required": int(threshold),
            "reward": label,
            "remaining": max(0, int(threshold) - int(valid_count)),
            "includes_discover_boost": False,
        }
    return None


def sync_referral_rewards_for_inviter(db: Session, inviter: User | None, *, source: str = "auto") -> list[dict]:
    """
    Grant all eligible milestones for inviter. Idempotent (unique milestone rows).
    Does not commit — caller must commit.
    """
    out: list[dict] = []
    if not inviter or getattr(inviter, "is_banned", False):
        return out

    valid_count = count_valid_referrals(db, inviter.id)
    granted = granted_milestone_keys(db, inviter.id)

    for threshold, days, key, _label in MILESTONES:
        if key in granted:
            continue
        if valid_count < threshold:
            continue

        row = ReferralRewardGrant(user_id=inviter.id, milestone_key=key, premium_days=int(days))
        db.add(row)
        _extend_premium_until(db, inviter, days)
        db.add(
            AnalyticsEvent(
                user_id=inviter.id,
                name="referral_reward_available",
                payload_json=json.dumps({"milestone_key": key, "source": source}),
            )
        )
        db.add(
            AnalyticsEvent(
                user_id=inviter.id,
                name="referral_premium_granted",
                payload_json=json.dumps({"milestone_key": key, "premium_days": int(days), "source": source}),
            )
        )
        if source == "manual":
            db.add(
                AnalyticsEvent(
                    user_id=inviter.id,
                    name="referral_reward_claimed",
                    payload_json=json.dumps({"milestone_key": key, "premium_days": int(days)}),
                )
            )
        granted.add(key)
        out.append({"milestone_key": key, "premium_days": int(days)})

    return out


def referral_abuse_flags(db: Session, since: datetime) -> list[dict]:
    """
    Aggregate-only signals: duplicate email patterns under one referrer, high same-day velocity.
    No private message content; uses email fingerprints only for pattern counts.
    """
    rows = (
        db.query(User)
        .filter(User.created_at >= since, User.referred_by_user_id.isnot(None))
        .all()
    )
    by_ref: dict[int, list[User]] = defaultdict(list)
    for u in rows:
        rid = int(u.referred_by_user_id or 0)
        if rid:
            by_ref[rid].append(u)

    flags: list[dict] = []
    for ref_id, us in by_ref.items():
        real = [u for u in us if not u.is_demo and not u.is_banned and not u.is_deleted]
        if len(real) < 3:
            continue
        fp_counts: dict[str, int] = defaultdict(int)
        day_counts: dict[str, int] = defaultdict(int)
        for u in real:
            fp = referral_identity_fingerprint(u.email) or f"user:{u.id}"
            fp_counts[fp] += 1
            dkey = u.created_at.date().isoformat() if u.created_at else ""
            day_counts[dkey] += 1
        dup_extra = sum(max(0, c - 1) for c in fp_counts.values())
        if dup_extra >= 2:
            flags.append(
                {
                    "referrer_user_id": int(ref_id),
                    "reason": "duplicate_email_pattern",
                    "score": int(dup_extra),
                }
            )
        max_day = max(day_counts.values()) if day_counts else 0
        if max_day >= 12:
            flags.append(
                {
                    "referrer_user_id": int(ref_id),
                    "reason": "high_same_day_referrals",
                    "score": int(max_day),
                }
            )
    return flags[:50]
