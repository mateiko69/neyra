from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GrowthConfig:
    # Nudges
    max_nudges_per_day: int = 3
    nudge_cooldown_minutes: int = 120

    # Notifications (non-transactional nudges; match/message pushes use separate rules)
    max_push_per_day: int = 3
    push_cooldown_minutes: int = 180
    # Hard cap for real-time match/message pushes (still non-spammy vs message floods)
    max_transactional_push_per_day: int = 12
    max_in_app_per_day: int = 8

    # Engagement thresholds
    inactive_hours_low: int = 36
    inactive_hours_medium: int = 12

    # Paywall triggers
    free_ai_reply_limit_per_day: int = 3
    free_openers_limit_per_day: int = 10

    # Rewards
    streak_reward_every: int = 3


DEFAULT_GROWTH_CONFIG = GrowthConfig()

