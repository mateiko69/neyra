from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MonetizationConfig:
    # Anti-spam paywalls
    paywall_cooldown_hours: int = 24

    # Trial / discounts
    trial_days: int = 3
    first_time_discount_percent: int = 30

    # Free AI limits (soft-gated features only; never block messaging)
    free_reply_suggestions_per_day: int = 8
    free_conversation_analyses_per_day: int = 3


DEFAULT_MONETIZATION_CONFIG = MonetizationConfig()

