"""Plan tiers, Paddle price mapping, and per-plan feature knobs (limits + UX flags)."""

from __future__ import annotations

from dataclasses import dataclass

from app.core.config import settings

# Product handles (documentation / checkout custom_data.plan_key)
PRODUCT_PREMIUM_MONTHLY = "premium_monthly"
PRODUCT_PREMIUM_PLUS_MONTHLY = "premium_plus_monthly"

INTERNAL_PLANS = frozenset({"free", "premium", "premium_plus"})


def normalize_internal_plan(plan: str | None) -> str:
    p = str(plan or "free").strip().lower()
    if p in {"premium_monthly", "premium"}:
        return "premium"
    if p in {"premium_plus_monthly", "premium+", "premium_plus"}:
        return "premium_plus"
    if p == "vip":
        return "premium_plus"
    return "free" if p not in INTERNAL_PLANS else p


def price_id_to_internal_plan(price_id: str | None) -> str | None:
    pid = str(price_id or "").strip()
    if not pid:
        return None
    prem = str(getattr(settings, "PADDLE_PRICE_ID_PREMIUM_MONTHLY", "") or "").strip()
    plus = str(getattr(settings, "PADDLE_PRICE_ID_PREMIUM_PLUS_MONTHLY", "") or "").strip()
    if prem and pid == prem:
        return "premium"
    if plus and pid == plus:
        return "premium_plus"
    return None


@dataclass(frozen=True)
class PlanEntitlements:
    can_see_who_liked_you: bool
    unlimited_ai: bool
    ai_reply_daily_cap: int | None  # None = unlimited
    ai_context_messages: int
    daily_boost_allowance: int
    can_reopen_chat: bool
    enable_ai_timing_decision: bool
    enable_chat_revive: bool
    enable_meeting_readiness: bool
    priority_in_discover: bool


def entitlements_for_plan(plan: str | None) -> PlanEntitlements:
    tier = normalize_internal_plan(plan)
    if tier == "premium_plus":
        return PlanEntitlements(
            can_see_who_liked_you=True,
            unlimited_ai=True,
            ai_reply_daily_cap=None,
            ai_context_messages=50,
            daily_boost_allowance=5,
            can_reopen_chat=True,
            enable_ai_timing_decision=True,
            enable_chat_revive=True,
            enable_meeting_readiness=True,
            priority_in_discover=True,
        )
    if tier == "premium":
        return PlanEntitlements(
            can_see_who_liked_you=False,
            unlimited_ai=False,
            ai_reply_daily_cap=100,
            ai_context_messages=50,
            daily_boost_allowance=1,
            can_reopen_chat=True,
            enable_ai_timing_decision=False,
            enable_chat_revive=True,
            enable_meeting_readiness=True,
            priority_in_discover=True,
        )
    return PlanEntitlements(
        can_see_who_liked_you=False,
        unlimited_ai=False,
        ai_reply_daily_cap=8,
        ai_context_messages=3,
        daily_boost_allowance=0,
        can_reopen_chat=False,
        enable_ai_timing_decision=False,
        enable_chat_revive=False,
        enable_meeting_readiness=False,
        priority_in_discover=False,
    )
