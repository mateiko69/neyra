from __future__ import annotations

import re

from app.domain.matching.profile_quality import ProfileQualityEvaluator
from app.domain.matching.utils import clamp_int
from app.domain.trust_and_safety.config import SCAM_PHRASES, SUSPICIOUS_BIO_PHRASES
from app.domain.trust_and_safety.types import ProfileRiskResult
from app.models.profile import Profile


class ProfileRiskEvaluator:
    """Evaluates profile trust risk + quality (no attractiveness scoring)."""

    @staticmethod
    def evaluate_profile_risk(profile: Profile | None) -> ProfileRiskResult:
        if profile is None:
            return ProfileRiskResult(
                risk_score=90,
                flags=["missing_profile"],
                quality_score=0,
                recommended_actions=["require_review"],
            )

        flags: list[str] = []
        actions: list[str] = []
        risk = 0

        bio = (getattr(profile, "bio", "") or "").strip()
        bio_l = bio.lower()
        photos = [x.strip() for x in (getattr(profile, "photo_urls", "") or "").split(",") if x.strip()]

        if len(bio) < 20:
            risk += 12
            flags.append("very_short_bio")
            actions.append("nudge_add_bio")

        if len(photos) <= 1:
            risk += 10
            flags.append("too_few_photos")
            actions.append("nudge_add_photos")

        # Keyword stuffing / repetitive text
        words = [w for w in re.split(r"[^a-zA-Zа-яА-Я0-9']+", bio_l) if w]
        if words:
            unique_ratio = len(set(words)) / len(words)
            if len(words) >= 30 and unique_ratio < 0.55:
                risk += 14
                flags.append("keyword_stuffing")

        if any(p in bio_l for p in SUSPICIOUS_BIO_PHRASES):
            risk += 55
            flags.append("external_contact_in_bio")
            actions.append("require_review")

        if any(p in bio_l for p in SCAM_PHRASES):
            risk += 18
            flags.append("suspicious_money_phrase")
            actions.append("require_review")

        # Field consistency
        goal = (getattr(profile, "relationship_goal", "") or "").strip()
        if not goal:
            risk += 8
            flags.append("missing_relationship_goal")

        age = getattr(profile, "age", None)
        if age is None:
            risk += 6
            flags.append("missing_age")

        quality = ProfileQualityEvaluator.evaluate(profile)
        quality_score = quality.overall_quality
        if quality_score < 50:
            risk += 10
            flags.append("low_profile_quality")

        risk_score = clamp_int(risk)
        if risk_score >= 85 and "require_review" not in actions:
            actions.append("require_review")

        return ProfileRiskResult(
            risk_score=risk_score,
            flags=sorted(set(flags)),
            quality_score=quality_score,
            recommended_actions=sorted(set(actions)),
        )

