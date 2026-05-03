"""Canonical profile verification state (client + ranking).

`verification_status` is the source of truth for `is_verified`.
Legacy DB values `approved` are treated as `verified` until migrations backfill.

API responses use consumer-friendly tokens: pending | approved | rejected | none
(DB keeps `verified` for approved users).
"""

from __future__ import annotations

from app.models.profile import Profile

VERIFICATION_POSE_CHALLENGES: frozenset[str] = frozenset({"turn_head_left", "smile", "raise_hand"})


def normalize_verification_status(raw: str | None) -> str:
    s = (raw or "none").strip().lower()
    if s == "approved":
        return "verified"
    if s == "pending_review":
        return "pending"
    if s in ("none", "pending", "verified", "rejected"):
        return s
    return "none"


def is_verified_profile(profile: Profile | None) -> bool:
    if not profile:
        return False
    return normalize_verification_status(getattr(profile, "verification_status", None)) == "verified"


def should_show_verified_badge(profile: Profile | None) -> bool:
    if not is_verified_profile(profile):
        return False
    if not bool(getattr(profile, "verification_badge_visible", True)):
        return False
    return True


def verification_status_for_api(profile: Profile | None) -> str:
    """UI + mobile: none | pending | approved | rejected."""
    if not profile:
        return "none"
    raw = normalize_verification_status(getattr(profile, "verification_status", None))
    if raw == "verified":
        return "approved"
    if raw == "pending":
        return "pending"
    if raw == "rejected":
        return "rejected"
    return "none"


def verification_type_for_api(profile: Profile | None) -> str:
    """Product vocabulary: selfie | photo | manual."""
    if not profile:
        return "manual"
    raw = (getattr(profile, "verification_type", None) or "manual").strip().lower()
    if raw == "selfie":
        return "selfie"
    if raw == "photo":
        return "photo"
    return "manual"
