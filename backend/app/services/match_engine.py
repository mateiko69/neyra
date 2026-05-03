from app.application.use_cases.matching.evaluate_compatibility import evaluate_compatibility
from app.models.profile import Profile


class MatchEngine:
    """Backward-compatible wrapper around the new compatibility engine."""

    @classmethod
    def score(cls, me: Profile, other: Profile) -> tuple[int, list[str]]:
        res = evaluate_compatibility(me, other)
        return res.compatibility_score, res.top_reasons
