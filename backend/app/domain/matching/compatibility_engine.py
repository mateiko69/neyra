from __future__ import annotations

from dataclasses import dataclass

from app.domain.matching.config import DEFAULT_WEIGHTS, CompatibilityWeights, ScoringConstants
from app.domain.matching.conversation_potential import ConversationPotentialScorer
from app.domain.matching.profile_quality import ProfileQualityEvaluator
from app.domain.matching.types import CompatibilityResult
from app.domain.matching.utils import clamp_int, jaccard_similarity, normalize_tokens, safe_lower, split_csv
from app.models.profile import Profile


@dataclass(frozen=True)
class _Component:
    key: str
    score: int
    reasons: list[str]
    warnings: list[str]


class CompatibilityEngine:
    """Multi-signal, explainable compatibility engine for NEYRA.

    Design goals:
    - Deterministic + testable
    - Configurable weights
    - No attractiveness / beauty scoring
    - Produces short human-readable reasons + non-fatal warning flags
    """

    def __init__(self, weights: CompatibilityWeights = DEFAULT_WEIGHTS):
        self._weights = weights

    def evaluate(self, me: Profile | None, other: Profile | None) -> CompatibilityResult:
        components = [
            self._relationship_intent(me, other),
            self._interests_overlap(me, other),
            self._lifestyle_similarity(me, other),
            self._age_preference(me, other),
            self._city_proximity(me, other),
            self._profile_completeness(other),
            self._conversation_potential(other),
            self._behavioral_quality_placeholder(other),
        ]

        breakdown = {c.key: c.score for c in components}
        warnings = sorted({w for c in components for w in c.warnings})

        final = self._weighted_sum(breakdown)
        top_reasons = self._select_top_reasons(components)
        return CompatibilityResult(
            compatibility_score=final,
            score_breakdown=breakdown,
            top_reasons=top_reasons,
            warning_flags=warnings,
        )

    def _weighted_sum(self, breakdown: dict[str, int]) -> int:
        weights = {
            "relationship_intent_score": self._weights.relationship_intent_score,
            "interests_overlap_score": self._weights.interests_overlap_score,
            "lifestyle_similarity_score": self._weights.lifestyle_similarity_score,
            "age_preference_score": self._weights.age_preference_score,
            "city_proximity_score": self._weights.city_proximity_score,
            "profile_completeness_score": self._weights.profile_completeness_score,
            "conversation_potential_score": self._weights.conversation_potential_score,
            "behavioral_quality_score": self._weights.behavioral_quality_score,
        }
        total_w = sum(weights.values()) or 1.0
        s = 0.0
        for k, w in weights.items():
            s += (breakdown.get(k, 0) / 100.0) * w
        return clamp_int((s / total_w) * 100)

    def _select_top_reasons(self, components: list[_Component]) -> list[str]:
        candidates: list[str] = []
        for c in components:
            candidates.extend(c.reasons)
        # Deduplicate while preserving order
        seen: set[str] = set()
        out: list[str] = []
        for r in candidates:
            if r not in seen:
                out.append(r)
                seen.add(r)
        if len(out) < ScoringConstants.MIN_REASONS:
            out.append("potential_match")
        return out[: ScoringConstants.MAX_REASONS]

    def _relationship_intent(self, me: Profile | None, other: Profile | None) -> _Component:
        me_goal = safe_lower(getattr(me, "relationship_goal", None))
        other_goal = safe_lower(getattr(other, "relationship_goal", None))
        warnings: list[str] = []
        reasons: list[str] = []

        if not other_goal:
            warnings.append("unclear_relationship_goal")
            return _Component("relationship_intent_score", 40, reasons, warnings)

        if me_goal and me_goal == other_goal:
            reasons.append("same_relationship_goal")
            return _Component("relationship_intent_score", 100, reasons, warnings)

        if me_goal and me_goal != other_goal:
            return _Component("relationship_intent_score", 35, reasons, warnings)

        # If we don't know user's intent, stay neutral.
        return _Component("relationship_intent_score", 60, reasons, warnings)

    def _interests_overlap(self, me: Profile | None, other: Profile | None) -> _Component:
        a = normalize_tokens(split_csv(getattr(me, "interests", "")))
        b = normalize_tokens(split_csv(getattr(other, "interests", "")))
        sim = jaccard_similarity(a, b)
        score = clamp_int(sim * 100)
        reasons: list[str] = []
        if a and b and sim >= 0.25:
            reasons.append("shared_interests")
        warnings = ["weak_interest_signal"] if not b else []
        return _Component("interests_overlap_score", score, reasons, warnings)

    def _lifestyle_similarity(self, me: Profile | None, other: Profile | None) -> _Component:
        a = normalize_tokens(split_csv(getattr(me, "lifestyle_tags", "")))
        b = normalize_tokens(split_csv(getattr(other, "lifestyle_tags", "")))
        sim = jaccard_similarity(a, b)
        score = clamp_int(sim * 100)
        reasons: list[str] = []
        if a and b and sim >= 0.25:
            reasons.append("similar_communication_style")
        return _Component("lifestyle_similarity_score", score, reasons, [])

    def _age_preference(self, me: Profile | None, other: Profile | None) -> _Component:
        age = getattr(other, "age", None)
        min_age = getattr(me, "min_preferred_age", None)
        max_age = getattr(me, "max_preferred_age", None)
        if age is None:
            return _Component("age_preference_score", 60, [], ["incomplete_profile"])

        # Within preference => 100, outside => scaled penalty.
        if min_age is not None and age < min_age:
            diff = min_age - age
            return _Component("age_preference_score", clamp_int(60 - diff * 10), [], [])
        if max_age is not None and age > max_age:
            diff = age - max_age
            return _Component("age_preference_score", clamp_int(60 - diff * 10), [], [])
        return _Component("age_preference_score", 100, [], [])

    def _city_proximity(self, me: Profile | None, other: Profile | None) -> _Component:
        my_city = safe_lower(getattr(me, "city", None))
        other_city = safe_lower(getattr(other, "city", None))
        if not other_city:
            return _Component("city_proximity_score", 50, [], ["incomplete_profile"])
        if my_city and my_city == other_city:
            return _Component("city_proximity_score", 100, ["nearby_city"], [])
        if not my_city:
            return _Component("city_proximity_score", 60, [], [])
        return _Component("city_proximity_score", 35, [], [])

    def _profile_completeness(self, other: Profile | None) -> _Component:
        quality = ProfileQualityEvaluator.evaluate(other)
        score = quality.completion_level_score
        reasons: list[str] = []
        if score >= 80:
            reasons.append("strong_profile_quality")
        warnings = list(quality.warning_flags)
        if score < 60:
            if "low_profile_detail" not in warnings:
                warnings.append("low_profile_detail")
        return _Component("profile_completeness_score", score, reasons[:1], warnings)

    def _conversation_potential(self, other: Profile | None) -> _Component:
        quality = ProfileQualityEvaluator.evaluate(other)
        score, reasons = ConversationPotentialScorer.score(other, quality=quality)
        warnings: list[str] = []
        if score < 40:
            warnings.append("low_profile_detail")
        return _Component("conversation_potential_score", score, reasons, warnings)

    def _behavioral_quality_placeholder(self, other: Profile | None) -> _Component:
        # Placeholder until real on-platform behavior signals exist (reply rate, respect, etc.)
        return _Component("behavioral_quality_score", 50, [], [])

