from __future__ import annotations

from dataclasses import dataclass

from app.models.profile import Profile

from app.services.trust.verification_state import is_verified_profile


@dataclass(frozen=True)
class ProfileTrust:
    trust_score: int
    trust_level: str  # low|medium|high
    is_verified: bool


def _bucket(score: int) -> str:
    if score >= 75:
        return "high"
    if score >= 45:
        return "medium"
    return "low"


def compute_profile_trust(profile: Profile | None) -> ProfileTrust:
    if not profile:
        return ProfileTrust(trust_score=0, trust_level="low", is_verified=False)

    score = 0

    photos = [x.strip() for x in (getattr(profile, "photo_urls", "") or "").split(",") if x.strip()]
    if len(photos) >= 1:
        score += 35
    if len(photos) >= 3:
        score += 15

    bio = (getattr(profile, "bio", "") or "").strip()
    if len(bio) >= 80:
        score += 20
    elif len(bio) >= 40:
        score += 10

    interests = [x.strip() for x in (getattr(profile, "interests", "") or "").split(",") if x.strip()]
    if len(interests) >= 3:
        score += 10

    verified = is_verified_profile(profile)
    if verified:
        score += 20

    score = max(0, min(100, int(score)))
    return ProfileTrust(trust_score=score, trust_level=_bucket(score), is_verified=verified)

