"""Shared per-plan limits for AI features (chat context windows, etc.)."""

from __future__ import annotations

from app.services.monetization.plan_entitlements import entitlements_for_plan


def message_context_limit(plan_tier: str | None) -> int:
    return int(entitlements_for_plan(plan_tier).ai_context_messages)


CONTEXT_MESSAGES_FREE = entitlements_for_plan("free").ai_context_messages
CONTEXT_MESSAGES_PREMIUM = entitlements_for_plan("premium").ai_context_messages
CONTEXT_MESSAGES_PREMIUM_PLUS = entitlements_for_plan("premium_plus").ai_context_messages
