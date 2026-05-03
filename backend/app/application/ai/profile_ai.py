from __future__ import annotations

from app.core.config import settings
from app.models.profile import Profile
from app.services.ai.service import get_ai_provider


class ProfileAI:
    """Profile analysis/improvement assistance."""

    @staticmethod
    def analyze(profile: Profile | None) -> dict:
        if not settings.ENABLE_AI_SUGGESTIONS:
            return {"enabled": False, "message": "AI suggestions are currently disabled."}
        provider = get_ai_provider()
        return provider.analyze_profile(profile)

