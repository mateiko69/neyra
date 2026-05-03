from __future__ import annotations

import re
from dataclasses import dataclass

from app.models.profile import Profile


@dataclass(frozen=True)
class ProfileQuality:
    quality_flag: str  # ok|low_quality
    quality_reason: str  # internal bucket only


_GENERIC_BIO_PATTERNS = [
    r"^hi$",
    r"^hey$",
    r"^hello$",
    r"^just ask$",
    r"^ask me$",
    r"^i don't know( yet)?$",
    r"^no bio$",
    r"^new here$",
    r"^here for fun$",
]


def _norm_text(s: str) -> str:
    t = (s or "").strip().lower()
    t = re.sub(r"\s+", " ", t)
    t = re.sub(r"[^\w\s'іїєґ]+", "", t)
    return t.strip()


def compute_profile_quality(profile: Profile | None) -> ProfileQuality:
    if not profile:
        return ProfileQuality(quality_flag="low_quality", quality_reason="missing_profile")

    bio_raw = getattr(profile, "bio", "") or ""
    bio = _norm_text(bio_raw)
    photos = [x.strip() for x in (getattr(profile, "photo_urls", "") or "").split(",") if x.strip()]
    interests = [x.strip() for x in (getattr(profile, "interests", "") or "").split(",") if x.strip()]

    # Very short bio / empty bio.
    if len(bio) < 10:
        return ProfileQuality(quality_flag="low_quality", quality_reason="bio_empty_or_tiny")

    if len(bio) < 30 and len(photos) <= 1:
        return ProfileQuality(quality_flag="low_quality", quality_reason="one_photo_and_short_bio")

    # Generic template-like bios.
    for pat in _GENERIC_BIO_PATTERNS:
        if re.match(pat, bio):
            return ProfileQuality(quality_flag="low_quality", quality_reason="generic_bio_template")

    # Low-effort combo: minimal interests + minimal bio + 1 photo.
    if len(photos) <= 1 and len(interests) == 0 and len(bio) < 45:
        return ProfileQuality(quality_flag="low_quality", quality_reason="minimal_profile")

    return ProfileQuality(quality_flag="ok", quality_reason="ok")

