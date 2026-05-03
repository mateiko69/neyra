from __future__ import annotations

from app.domain.matching.utils import clamp_int
from app.domain.trust_and_safety.types import BotSignalsResult
from app.models.profile import Profile


class BotSignalDetector:
    """Heuristic bot signal detector (modular; ML can replace later).

    behavior_data is a dict to keep this decoupled from storage for now.
    Expected optional keys:
    - swipes_last_minute: int
    - messages_last_minute: int
    - repeated_opener_ratio: float (0..1)
    - identical_profile_template: bool
    """

    @staticmethod
    def detect_bot_signals(profile: Profile | None, behavior_data: dict | None) -> BotSignalsResult:
        data = behavior_data or {}
        signals: list[str] = []
        score = 0

        swipes = int(data.get("swipes_last_minute", 0) or 0)
        msgs = int(data.get("messages_last_minute", 0) or 0)
        rep = float(data.get("repeated_opener_ratio", 0) or 0)
        template = bool(data.get("identical_profile_template", False))

        if swipes >= 80:
            score += 30
            signals.append("ultra_fast_swiping")
        elif swipes >= 40:
            score += 18
            signals.append("fast_swiping")

        if msgs >= 30:
            score += 28
            signals.append("ultra_fast_messaging")
        elif msgs >= 15:
            score += 16
            signals.append("fast_messaging")

        if rep >= 0.8:
            score += 26
            signals.append("repeated_opener_to_many")
        elif rep >= 0.6:
            score += 16
            signals.append("high_opener_reuse")

        if template:
            score += 18
            signals.append("template_profile_pattern")

        bio = (getattr(profile, "bio", "") or "").strip()
        if len(bio) <= 10:
            score += 8
            signals.append("low_effort_profile_text")

        return BotSignalsResult(bot_probability=clamp_int(score), signals=sorted(set(signals)))

