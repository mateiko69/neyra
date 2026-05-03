from __future__ import annotations

from app.core.config import settings
from app.models.profile import Profile
from app.services.match_engine import MatchEngine as LegacyMatchEngine


class CompatibilityScorer:
    """Compatibility scoring facade.

    Keeps existing scoring logic but provides a stable module boundary for
    future advanced matching/ranking work.
    """

    @staticmethod
    def score(me: Profile, other: Profile) -> tuple[int, list[str]]:
        if not settings.ENABLE_ADVANCED_MATCHING:
            return 50, ["Basic matching enabled (advanced matching is disabled)."]
        return LegacyMatchEngine.score(me, other)

