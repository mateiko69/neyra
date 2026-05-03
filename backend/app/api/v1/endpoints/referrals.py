"""Referral / invite links for authenticated users."""

from __future__ import annotations

from sqlalchemy import func
from sqlalchemy.orm import Session
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.api_errors import api_error
from app.api.deps import get_current_user, get_db
from app.models.analytics_event import AnalyticsEvent
from app.models.user import User
from app.services.analytics import track_event
from app.services.referral_rewards import (
    count_valid_referrals,
    granted_milestone_keys,
    list_earned_reward_rows,
    next_reward_payload,
    sync_referral_rewards_for_inviter,
)
from app.models.referral_reward_grant import ReferralRewardGrant
from app.services.referral_rewards import _extend_premium_until
from app.services.referrals import (
    build_invite_link,
    ensure_referral_code_for_user,
    normalize_referral_code,
    resolve_referrer_user,
    try_apply_referral_to_user,
)

router = APIRouter()

_INVITE_EVENTS = ("invite_link_copied", "invite_native_share_clicked")


class ReferralClaimIn(BaseModel):
    referral_code: str = Field(..., min_length=4, max_length=32)


def _earned_rewards_payload(db: Session, user_id: int) -> list[dict]:
    rows = list_earned_reward_rows(db, user_id)
    return [
        {
            "milestone_key": g.milestone_key,
            "premium_days": int(g.premium_days),
            "granted_at": g.created_at.isoformat() if g.created_at else None,
        }
        for g in rows
    ]


@router.get("/me")
def referrals_me(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    code = ensure_referral_code_for_user(db, current_user)
    sync_referral_rewards_for_inviter(db, current_user, source="auto")
    db.commit()
    db.refresh(current_user)

    invites_count = int(
        db.query(func.count(AnalyticsEvent.id))
        .filter(
            AnalyticsEvent.user_id == current_user.id,
            AnalyticsEvent.name.in_(_INVITE_EVENTS),
        )
        .scalar()
        or 0
    )
    joined_count = int(
        db.query(func.count(User.id)).filter(User.referred_by_user_id == current_user.id).scalar() or 0
    )
    valid_referrals_count = count_valid_referrals(db, current_user.id)
    granted = granted_milestone_keys(db, current_user.id)
    earned = _earned_rewards_payload(db, current_user.id)
    next_reward = next_reward_payload(valid_referrals_count, granted)

    return {
        "invite_link": build_invite_link(code),
        "referral_code": code,
        "invites_count": invites_count,
        "joined_count": joined_count,
        "premium_rewards": earned,
        "valid_referrals_count": int(valid_referrals_count),
        "next_reward": next_reward,
        "earned_rewards": earned,
    }


@router.post("/claim")
def referrals_claim(
    payload: ReferralClaimIn,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.referred_by_user_id:
        raise HTTPException(status_code=400, detail=api_error("referral.already_claimed"))

    normalized = normalize_referral_code(payload.referral_code)
    referrer = resolve_referrer_user(db, normalized)
    if not referrer:
        raise HTTPException(status_code=400, detail=api_error("referral.invalid"))

    if referrer.id == current_user.id:
        raise HTTPException(status_code=400, detail=api_error("referral.self"))

    if not try_apply_referral_to_user(db, current_user, normalized):
        raise HTTPException(status_code=400, detail=api_error("referral.invalid"))

    db.commit()
    track_event(db, "referral_claimed", user_id=current_user.id, payload={"referrer_user_id": referrer.id})
    return {"ok": True, "referrer_user_id": referrer.id}


@router.post("/claim-reward")
def referrals_claim_reward(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if getattr(current_user, "is_banned", False):
        return {"status": "no_reward_available"}
    granted = sync_referral_rewards_for_inviter(db, current_user, source="manual")
    db.commit()
    db.refresh(current_user)
    if not granted:
        return {"status": "no_reward_available"}
    return {
        "status": "awarded",
        "rewards": granted,
        "premium_until": current_user.premium_until.isoformat() if current_user.premium_until else None,
    }


@router.post("/first-share")
def referrals_first_share(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """
    Content-first viral reward: first successful share gets +3 days Premium.
    Idempotent via unique (user_id, milestone_key).
    """
    if getattr(current_user, "is_banned", False):
        return {"status": "no_reward_available"}
    key = "share_1"
    existing = (
        db.query(ReferralRewardGrant)
        .filter(ReferralRewardGrant.user_id == int(current_user.id), ReferralRewardGrant.milestone_key == key)
        .first()
    )
    if existing:
        return {"status": "already_awarded"}
    row = ReferralRewardGrant(user_id=int(current_user.id), milestone_key=key, premium_days=3)
    db.add(row)
    _extend_premium_until(db, current_user, 3)
    track_event(db, "viral_first_share_reward_granted", user_id=current_user.id, payload={"premium_days": 3})
    db.commit()
    db.refresh(current_user)
    return {
        "status": "awarded",
        "premium_days": 3,
        "premium_until": current_user.premium_until.isoformat() if current_user.premium_until else None,
    }
