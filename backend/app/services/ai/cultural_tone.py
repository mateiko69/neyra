from __future__ import annotations

from app.services.ai.ai_request_locale import normalize_ai_request_locale

# Soft communication hints only — not stereotypes or personality rules.
_CULTURAL_TONE_BY_PRIMARY: dict[str, str] = {
    "en": "warm, direct, light humor",
    "uk": "warm, sincere, lightly playful",
    "ru": "confident, concise, respectful",
    "es": "expressive, warm, playful",
    "pt": "warm, emotional, relaxed",
    "ja": "polite, subtle, indirect, gentle",
    "ko": "polite, light, respectful",
    "zh": "respectful, calm, not too intense",
    "ar": "respectful, modest, warm",
    "tr": "warm, confident, lightly playful",
}

_DEFAULT_TONE = "natural, respectful, friendly"


def get_cultural_tone(locale: str | None) -> str:
    """
    Return a short, soft style hint for the locale (dating-safe, non-stereotyping).
    Used in prompts only as guidance — never as a rigid persona.
    """
    raw = (locale or "").strip()
    loc = normalize_ai_request_locale(locale)
    # If the caller asked for an unknown locale (e.g. "xx"), do not silently fall back to English tone.
    # Use a safe, generic default instead.
    if raw and loc == "en":
        raw_primary = raw.replace("_", "-").split("-", 1)[0].strip().lower()
        if raw_primary and raw_primary not in _CULTURAL_TONE_BY_PRIMARY and raw_primary != "en":
            return _DEFAULT_TONE
    if loc.startswith("zh"):
        return _CULTURAL_TONE_BY_PRIMARY["zh"]
    primary = loc.split("-", 1)[0] if loc else "en"
    return _CULTURAL_TONE_BY_PRIMARY.get(primary, _DEFAULT_TONE)


def cultural_tone_prompt_lines(locale: str | None) -> str:
    """Shared block for model prompts (generation + rewrite + translate fallbacks)."""
    loc = normalize_ai_request_locale(locale)
    tone = get_cultural_tone(loc)
    return (
        f"Write in locale: {loc}.\n"
        f"Use this cultural tone softly: {tone}.\n"
        "Do not stereotype. Do not exaggerate. Keep it natural.\n"
        "Stay respectful, dating-safe: never sexualize, pressure, manipulate, or shame."
    )
