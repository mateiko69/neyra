from __future__ import annotations

import random

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.models.user import User
from app.services.monetization.subscription_service import SubscriptionService
from app.services.retention.daily_boosts import (
    FREE_TIER_AI_REPLY_SLOTS_PER_DAY,
    consume_daily_boost_slot,
    get_daily_boosts_state,
    save_daily_boosts_state,
    streak_bonus_ai_chat_fetches,
    today_utc_iso,
)

router = APIRouter()


class DailyBoostsOut(BaseModel):
    day: str
    opener_remaining: int
    reply_remaining: int
    reveal_remaining: int
    revive_remaining: int
    streak_days: int
    streak_bonus_ai_chat: int
    show_banner: bool
    curiosity_like: bool


def _out_from_state(st: dict) -> DailyBoostsOut:
    opener_remaining = 0 if bool(st.get("opener_used")) else 1
    reply_uses = int(st.get("reply_uses") or 0)
    reply_remaining = max(0, int(FREE_TIER_AI_REPLY_SLOTS_PER_DAY) - reply_uses)
    reveal_remaining = 0 if bool(st.get("reveal_used")) else 1
    revive_remaining = 0 if bool(st.get("revive_used")) else 1
    streak_days = int(st.get("streak_days") or 1)
    show_banner = not bool(st.get("banner_dismissed")) and (
        opener_remaining + reply_remaining + reveal_remaining + revive_remaining
    ) > 0
    return DailyBoostsOut(
        day=str(st.get("day") or today_utc_iso()),
        opener_remaining=opener_remaining,
        reply_remaining=reply_remaining,
        reveal_remaining=reveal_remaining,
        revive_remaining=revive_remaining,
        streak_days=streak_days,
        streak_bonus_ai_chat=streak_bonus_ai_chat_fetches(streak_days),
        show_banner=show_banner,
        curiosity_like=False,
    )


@router.get("/boosts", response_model=DailyBoostsOut)
def daily_boosts(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        plan = SubscriptionService().get_active_plan(db, int(current_user.id))
    except Exception:
        plan = "free"

    st = get_daily_boosts_state(db, user_id=int(current_user.id))

    if plan in {"premium", "premium_plus"}:
        return DailyBoostsOut(
            day=today_utc_iso(),
            opener_remaining=999,
            reply_remaining=999,
            reveal_remaining=999,
            revive_remaining=999,
            streak_days=int(st.get("streak_days") or 1),
            streak_bonus_ai_chat=0,
            show_banner=False,
            curiosity_like=False,
        )

    curiosity_like = False
    if not bool(st.get("curiosity_like_shown")):
        if random.random() < 0.35:
            curiosity_like = True
            st["curiosity_like_shown"] = True
            st = save_daily_boosts_state(db, user_id=int(current_user.id), value=st)

    data = _out_from_state(st).model_dump()
    if "curiosity_like" in data:
        del data["curiosity_like"]
    return DailyBoostsOut(
        curiosity_like=curiosity_like,
        **data,
    )


class ConsumeDailyBoostIn(BaseModel):
    boost_type: str


@router.post("/consume", response_model=DailyBoostsOut)
def consume_daily_boost(payload: ConsumeDailyBoostIn, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        plan = SubscriptionService().get_active_plan(db, int(current_user.id))
    except Exception:
        plan = "free"
    if plan in {"premium", "premium_plus"}:
        st = get_daily_boosts_state(db, user_id=int(current_user.id))
        return DailyBoostsOut(
            day=today_utc_iso(),
            opener_remaining=999,
            reply_remaining=999,
            reveal_remaining=999,
            revive_remaining=999,
            streak_days=int(st.get("streak_days") or 1),
            streak_bonus_ai_chat=0,
            show_banner=False,
            curiosity_like=False,
        )
    bt = str(payload.boost_type or "").strip().lower()
    if bt not in {"opener", "reply", "reveal", "revive"}:
        raise HTTPException(status_code=400, detail="Invalid boost_type")
    consume_daily_boost_slot(db, user_id=int(current_user.id), boost_type=bt)
    st = get_daily_boosts_state(db, user_id=int(current_user.id))
    return _out_from_state(st)


@router.post("/dismiss-banner", response_model=DailyBoostsOut)
def dismiss_daily_banner(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    try:
        plan = SubscriptionService().get_active_plan(db, int(current_user.id))
    except Exception:
        plan = "free"
    if plan in {"premium", "premium_plus"}:
        st = get_daily_boosts_state(db, user_id=int(current_user.id))
        return DailyBoostsOut(
            day=today_utc_iso(),
            opener_remaining=999,
            reply_remaining=999,
            reveal_remaining=999,
            revive_remaining=999,
            streak_days=int(st.get("streak_days") or 1),
            streak_bonus_ai_chat=0,
            show_banner=False,
            curiosity_like=False,
        )
    st = get_daily_boosts_state(db, user_id=int(current_user.id))
    st["banner_dismissed"] = True
    st = save_daily_boosts_state(db, user_id=int(current_user.id), value=st)
    return DailyBoostsOut(**{**_out_from_state(st).model_dump(), "show_banner": False})
