from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ViralConfig:
    referral_base_url: str = "https://neyra.app/invite"

    # Referral rewards (activated users)
    reward_1_friend_premium_days: int = 1
    reward_3_friends_ai_unlimited_days: int = 3
    reward_10_friends_profile_boost: bool = True

    # Streak thresholds
    streak_hot_days: int = 7
    streak_rising_days: int = 3


DEFAULT_VIRAL_CONFIG = ViralConfig()

