"""English names for UI locale codes — used in Gemini system prompts (respond ONLY in …)."""

from __future__ import annotations

from app.services.app_language import normalize_app_language

# ISO-oriented labels; extend when adding app locales.
_LOCALE_ENGLISH_NAME: dict[str, str] = {
    "en": "English",
    "uk": "Ukrainian",
    "ru": "Russian",
    "es": "Spanish",
    "pt": "Portuguese",
    "fr": "French",
    "de": "German",
    "it": "Italian",
    "pl": "Polish",
    "tr": "Turkish",
    "zh": "Chinese (Simplified)",
    "zh-TW": "Chinese (Traditional)",
    "ja": "Japanese",
    "ko": "Korean",
    "hi": "Hindi",
    "id": "Indonesian",
    "vi": "Vietnamese",
    "th": "Thai",
    "ar": "Arabic",
    "he": "Hebrew",
    "nl": "Dutch",
    "sv": "Swedish",
    "cs": "Czech",
    "ro": "Romanian",
    "hu": "Hungarian",
    "el": "Greek",
    "da": "Danish",
    "fi": "Finnish",
    "no": "Norwegian",
    "bg": "Bulgarian",
}


def english_language_name_for_ai_prompt(locale_code: str | None) -> str:
    """Human-readable English name for strict language instructions to the model."""
    code = normalize_app_language(locale_code or "en")
    return _LOCALE_ENGLISH_NAME.get(code, "the user's selected UI language")

