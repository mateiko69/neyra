from __future__ import annotations

from dataclasses import dataclass

from app.application.use_cases.matching.evaluate_compatibility import evaluate_compatibility
from app.domain.matching.types import CompatibilityResult
from app.models.profile import Profile


@dataclass(frozen=True)
class RankedCandidate:
    profile: Profile
    compatibility: CompatibilityResult


class RankingEngineService:
    """Ranks candidates by compatibility (deterministic, explainable)."""

    @staticmethod
    def rank(me: Profile | None, candidates: list[Profile]) -> list[RankedCandidate]:
        ranked: list[RankedCandidate] = []
        for p in candidates:
            ranked.append(RankedCandidate(profile=p, compatibility=evaluate_compatibility(me, p)))
        ranked.sort(key=lambda r: r.compatibility.compatibility_score, reverse=True)
        return ranked

