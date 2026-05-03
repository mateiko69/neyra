from __future__ import annotations

from dataclasses import dataclass

from app.domain.matching.config import ScoringConstants
from app.domain.matching.utils import clamp_int, normalize_tokens, split_csv
from app.models.profile import Profile


@dataclass(frozen=True)
class ProfileQuality:
    """Explainable profile quality scores (0..100)."""

    bio_quality_score: int
    photos_score: int
    interests_richness_score: int
    lifestyle_tags_score: int
    completion_level_score: int

    warning_flags: list[str]

    @property
    def overall_quality(self) -> int:
        # Simple average (kept predictable and easy to tune later).
        return clamp_int(
            (
                self.bio_quality_score
                + self.photos_score
                + self.interests_richness_score
                + self.lifestyle_tags_score
                + self.completion_level_score
            )
            / 5
        )


class ProfileQualityEvaluator:
    """Deterministic evaluator for profile quality and completeness.

    Important: this is NOT attractiveness scoring; it only measures information
    richness and completeness to support better conversations and matching.
    """

    @staticmethod
    def evaluate(profile: Profile | None) -> ProfileQuality:
        if profile is None:
            return ProfileQuality(
                bio_quality_score=0,
                photos_score=0,
                interests_richness_score=0,
                lifestyle_tags_score=0,
                completion_level_score=0,
                warning_flags=["incomplete_profile", "low_profile_detail", "weak_interest_signal"],
            )

        warnings: list[str] = []

        bio = (getattr(profile, "bio", "") or "").strip()
        bio_len = len(bio)

        if bio_len <= 0:
            warnings.append("low_profile_detail")
        bio_quality = 0
        if bio_len >= ScoringConstants.BIO_MIN_LEN_FOR_BASELINE:
            bio_quality = 55
        if bio_len >= ScoringConstants.BIO_MIN_LEN_FOR_RICHNESS:
            bio_quality = 80
        # Bonus for having a question/prompt to start conversation
        if "?" in bio and bio_len >= ScoringConstants.BIO_MIN_LEN_FOR_BASELINE:
            bio_quality = clamp_int(bio_quality + 8)

        photos = split_csv(getattr(profile, "photo_urls", "") or "")
        photos_count = min(len(photos), ScoringConstants.MAX_PHOTOS_COUNTED)
        photos_score = clamp_int((photos_count / ScoringConstants.MAX_PHOTOS_COUNTED) * 100)
        if photos_count == 0:
            warnings.append("incomplete_profile")

        interests = normalize_tokens(split_csv(getattr(profile, "interests", "") or ""))
        interests_count = len(interests)
        if interests_count == 0:
            warnings.append("weak_interest_signal")
        interests_richness_score = clamp_int(min(interests_count / ScoringConstants.GOOD_INTERESTS_MIN, 1.0) * 100)

        tags = normalize_tokens(split_csv(getattr(profile, "lifestyle_tags", "") or ""))
        tags_count = len(tags)
        lifestyle_tags_score = clamp_int(min(tags_count / ScoringConstants.GOOD_LIFESTYLE_TAGS_MIN, 1.0) * 100)

        completion_points = 0
        completion_points += 1 if bio_len >= ScoringConstants.BIO_MIN_LEN_FOR_BASELINE else 0
        completion_points += 1 if photos_count >= 1 else 0
        completion_points += 1 if interests_count >= 2 else 0
        completion_points += 1 if tags_count >= 1 else 0
        completion_points += 1 if (getattr(profile, "relationship_goal", "") or "").strip() else 0
        completion_level_score = clamp_int((completion_points / 5) * 100)
        if completion_level_score < 60:
            warnings.append("incomplete_profile")

        return ProfileQuality(
            bio_quality_score=bio_quality,
            photos_score=photos_score,
            interests_richness_score=interests_richness_score,
            lifestyle_tags_score=lifestyle_tags_score,
            completion_level_score=completion_level_score,
            warning_flags=sorted(set(warnings)),
        )

