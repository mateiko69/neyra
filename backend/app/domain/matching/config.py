from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CompatibilityWeights:
    """Weights for compatibility score components.

    Each component score is expected to be in the 0..100 range.
    Weights are relative and get normalized when calculating the final score.
    """

    relationship_intent_score: float = 1.2
    interests_overlap_score: float = 1.0
    lifestyle_similarity_score: float = 0.8
    age_preference_score: float = 0.9
    city_proximity_score: float = 0.6
    profile_completeness_score: float = 0.7
    conversation_potential_score: float = 1.1
    behavioral_quality_score: float = 0.4  # placeholder until real behavioral data exists


DEFAULT_WEIGHTS = CompatibilityWeights()


class ScoringConstants:
    """Non-magic scoring constants grouped in one place."""

    BIO_MIN_LEN_FOR_RICHNESS = 80
    BIO_MIN_LEN_FOR_BASELINE = 40
    MAX_REASONS = 4
    MIN_REASONS = 2

    # Profile completeness components
    MAX_PHOTOS_COUNTED = 6
    GOOD_PHOTOS_MIN = 3
    GOOD_INTERESTS_MIN = 5
    GOOD_LIFESTYLE_TAGS_MIN = 3

