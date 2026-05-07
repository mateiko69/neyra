"""Canonical app locale codes (aligned with frontend `lib/i18n/locales.ts`)."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.profile import Profile
from app.models.user import User

# BCP-47 style codes used by Chat Brain / demo messages
SUPPORTED_APP_LANGUAGES: frozenset[str] = frozenset(
    {
        "en",
        "uk",
        "ru",
        "es",
        "pt",
        "fr",
        "de",
        "it",
        "pl",
        "tr",
        "zh",
        "zh-TW",
        "ja",
        "ko",
        "hi",
        "id",
        "vi",
        "th",
        "ar",
        "he",
        "nl",
        "sv",
        "cs",
        "ro",
        "hu",
        "el",
        "da",
        "fi",
        "no",
        "bg",
    }
)

_ALIASES: dict[str, str] = {
    "ua": "uk",
    "zh_cn": "zh",
    "zhcn": "zh",
    "zh-cn": "zh",
    "zh_tw": "zh-TW",
    "zhtw": "zh-TW",
    "zh-tw": "zh-TW",
    "in": "id",
    "iw": "he",
    "nb": "no",
    "nn": "no",
}


def normalize_app_language(code: str | None) -> str:
    """Normalize raw language tag to a supported app code; default English."""
    raw = (code or "").strip()
    if not raw:
        return "en"
    s = raw.lower().replace("_", "-")
    if s in _ALIASES:
        return _ALIASES[s]
    if s.startswith("uk") or s == "ua":
        return "uk"
    if s.startswith("en"):
        return "en"
    for supported in SUPPORTED_APP_LANGUAGES:
        if s == supported.lower():
            return supported
    if s in ("zh-cn", "zh-hans"):
        return "zh"
    if s in ("zh-tw", "zh-hant", "zh-hk"):
        return "zh-TW"
    primary = s.split("-", 1)[0]
    if primary in SUPPORTED_APP_LANGUAGES:
        return primary
    return "en"


def resolve_ai_request_locale(value: str | None) -> str:
    """
    Output language for AI endpoints: use ONLY the locale from the HTTP request body.
    Missing or blank → "en". No profile/geo/Accept-Language inference here.
    """
    return normalize_app_language(value)


def locale_from_accept_language_header(header_value: str | None) -> str:
    """
    Pick the best supported app language from an Accept-Language header (RFC 7231-style list).
    Order matches typical browser lists (first choices win; ignore q-values for simplicity).
    """
    if not header_value:
        return ""
    tokens: list[str] = []
    for part in header_value.split(","):
        chunk = part.strip()
        if not chunk:
            continue
        lang_range = chunk.split(";", 1)[0].strip()
        if lang_range:
            tokens.append(lang_range)
    for t in tokens:
        n = normalize_app_language(t)
        if n and n != "en":
            return n
    for t in tokens:
        n = normalize_app_language(t)
        if n:
            return n
    return ""


def resolve_recipient_language(db: Session, recipient_user_id: int) -> str:
    """
    Language for messages *to* recipient_user_id (real user receiving demo bot text).
    Priority: profile.preferred_language → user.preferred_language (if column exists) → en.
    Client locale should be synced into profile.preferred_language when the user changes UI language.
    """
    uid = int(recipient_user_id)
    profile = db.query(Profile).filter(Profile.user_id == uid).first()
    user = db.query(User).filter(User.id == uid).first()
    raw = ""
    if profile and getattr(profile, "preferred_language", None):
        raw = str(profile.preferred_language or "").strip()
    if not raw and user is not None:
        raw = str(getattr(user, "preferred_language", "") or "").strip()
    return normalize_app_language(raw or "en")
