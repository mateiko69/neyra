from __future__ import annotations

import re

from app.services.app_language import normalize_app_language

_UK_SPECIFIC_RE = re.compile(r"[іїєґІЇЄҐ]")
_CYRILLIC_RE = re.compile(r"[\u0400-\u04FF]")
_LATIN_RE = re.compile(r"[A-Za-z]")
_CJK_RE = re.compile(r"[\u4E00-\u9FFF]")
_HIRAGANA_KATAKANA_RE = re.compile(r"[\u3040-\u30FF]")
_HANGUL_RE = re.compile(r"[\uAC00-\uD7AF]")
_ARABIC_RE = re.compile(r"[\u0600-\u06FF]")
_HEBREW_RE = re.compile(r"[\u0590-\u05FF]")
_DEVANAGARI_RE = re.compile(r"[\u0900-\u097F]")

_ES_HINT_RE = re.compile(r"\b(hola|cómo|como\s+estas|gracias|qué|que tal)\b", re.IGNORECASE)
_PT_HINT_RE = re.compile(r"\b(oi|tudo\s+bem|obrigad[oa]|você|voce|legal)\b", re.IGNORECASE)
_EN_HINT_RE = re.compile(r"\b(hey|hello|how are you|thanks|what's up|nice)\b", re.IGNORECASE)
_FR_HINT_RE = re.compile(r"\b(bonjour|ça va|ca va|merci|salut)\b", re.IGNORECASE)
_DE_HINT_RE = re.compile(r"\b(hallo|danke|wie geht|schön|schoen)\b", re.IGNORECASE)
_IT_HINT_RE = re.compile(r"\b(ciao|grazie|come stai)\b", re.IGNORECASE)
_PL_HINT_RE = re.compile(r"\b(cześć|czesc|dzięk|dziek|jak tam)\b", re.IGNORECASE)
_TR_HINT_RE = re.compile(r"\b(merhaba|nasılsın|nasilsin|teşekkür|tesekkur)\b", re.IGNORECASE)


def normalize_ai_locale_tag(raw: str | None) -> str:
    """Normalize locale tags to AI-supported canonical language keys."""
    loc = normalize_app_language(raw)
    # AI layer uses "zh" for Simplified Chinese; frontend may pass zh-CN.
    if loc == "zh-CN":
        return "zh"
    return loc or "en"


def detect_message_locale(message_text: str | None) -> str | None:
    """Deterministic, dependency-free script-based language detection."""
    text = (message_text or "").strip()
    if not text:
        return None
    if _HIRAGANA_KATAKANA_RE.search(text):
        return "ja"
    if _HANGUL_RE.search(text):
        return "ko"
    if _CJK_RE.search(text):
        return "zh"
    if _ARABIC_RE.search(text):
        return "ar"
    if _HEBREW_RE.search(text):
        return "he"
    if _DEVANAGARI_RE.search(text):
        return "hi"
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
        if _ES_HINT_RE.search(text):
            return "es"
        if _PT_HINT_RE.search(text):
            return "pt"
        if _FR_HINT_RE.search(text):
            return "fr"
        if _DE_HINT_RE.search(text):
            return "de"
        if _IT_HINT_RE.search(text):
            return "it"
        if _PL_HINT_RE.search(text):
            return "pl"
        if _TR_HINT_RE.search(text):
            return "tr"
        if _EN_HINT_RE.search(text):
            return "en"
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
