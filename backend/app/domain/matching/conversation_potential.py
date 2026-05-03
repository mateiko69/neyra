from __future__ import annotations

import re

from app.domain.matching.config import ScoringConstants
from app.domain.matching.profile_quality import ProfileQuality
from app.domain.matching.utils import clamp_int, normalize_tokens, split_csv
from app.models.profile import Profile


class ConversationPotentialScorer:
    """Estimates how easy it is to start a good conversation (0..100).

    Uses only content richness and prompt-worthy details.
    Does NOT use attractiveness proxies or personality claims.
    """

    PROMPTY_PHRASES = (
        "ask me about",
        "i love",
        "i’m into",
        "i'm into",
        "currently",
        "recently",
        "obsessed with",
        "favorite",
    )

    @classmethod
    def score(cls, profile: Profile | None, quality: ProfileQuality | None = None) -> tuple[int, list[str]]:
        if profile is None:
            return 0, ["Incomplete profile makes conversation harder"]

        bio = (profile.bio or "").strip()
        interests = normalize_tokens(split_csv(profile.interests))

        reasons: list[str] = []
        base = 20

        # Bio richness
        if len(bio) >= ScoringConstants.BIO_MIN_LEN_FOR_BASELINE:
            base += 25
            reasons.append("Rich bio makes it easier to start a conversation")
        if len(bio) >= ScoringConstants.BIO_MIN_LEN_FOR_RICHNESS:
            base += 10

        # Interest specificity
        if len(interests) >= 3:
            base += 20
            reasons.append("Specific interests give clear conversation starters")
        elif len(interests) > 0:
            base += 10

        # Originality: simple heuristic (unique words / low repetition)
        words = [w for w in re.split(r"[^a-zA-Zа-яА-Я0-9']+", bio.lower()) if w]
        unique_ratio = (len(set(words)) / len(words)) if words else 0.0
        if unique_ratio >= 0.65 and len(words) >= 20:
            base += 10
            reasons.append("Original profile details increase conversation potential")

        # Prompt-worthy details
        bio_l = bio.lower()
        if any(p in bio_l for p in cls.PROMPTY_PHRASES) or "?" in bio:
            base += 10

        # Quality influences, but does not replace compatibility.
        if quality is not None:
            base += int((quality.overall_quality - 50) * 0.2)  # +/-10 max effect

        return clamp_int(base), reasons[:2]

