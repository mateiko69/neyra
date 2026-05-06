from __future__ import annotations

import re

from app.services.app_language import normalize_app_language

_UK_SPECIFIC_RE = re.compile(r"[іїєґІЇЄҐ]")
_CYRILLIC_RE = re.compile(r"[\u0400-\u04FF]")
_LATIN_RE = re.compile(r"[A-Za-z]")


def normalize_ai_locale_tag(raw: str | None) -> str:
    """Normalize locale tags to AI-supported canonical language keys."""
    loc = normalize_app_language(raw)
    if loc == "uk":
        return "uk"
    if loc == "ru":
        return "ru"
    if loc == "en":
        return "en"
    return "en"


def detect_message_locale(message_text: str | None) -> str | None:
    """Deterministic, dependency-free script-based language detection."""
    text = (message_text or "").strip()
    if not text:
        return None
    if _UK_SPECIFIC_RE.search(text):
        return "uk"
    cyr = len(_CYRILLIC_RE.findall(text))
    lat = len(_LATIN_RE.findall(text))
    alpha = cyr + lat
    if alpha < 2:
        return None
    if cyr >= max(2, lat):
        return "ru"
    if lat >= max(2, cyr):
        return "en"
    return None


def resolve_ai_locale_decision(
    *,
    latest_user_message: str | None,
    interface_locale: str | None,
    profile_locale: str | None,
) -> tuple[str, str]:
    """Return (locale, source) where source is message|interface|profile|fallback."""
    msg = detect_message_locale(latest_user_message)
    if msg:
        return (msg, "message")
    ui = normalize_ai_locale_tag(interface_locale)
    if interface_locale and ui:
        return (ui, "interface")
    prof = normalize_ai_locale_tag(profile_locale)
    if profile_locale and prof:
        return (prof, "profile")
    return ("en", "fallback")
