from __future__ import annotations

from typing import Final


SUPPORTED_LOCALES: Final[set[str]] = {
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
    "zh-tw",
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
}


def normalize_locale(value: str | None) -> str:
    raw = (value or "").strip().replace("_", "-")
    if not raw:
        return "en"
    lower = raw.lower()

    # Chinese script variants (aligned with frontend `AppLocale`).
    if lower in {"zh-tw", "zh-hant", "zh-hk", "zh-mo"} or lower.startswith("zh-hant-"):
        return "zh-TW"
    if lower in {"zh-cn", "zh-hans", "zh-sg", "zh"} or lower.startswith("zh-hans-"):
        return "zh"
    if lower.startswith("zh-"):
        return "zh"

    # Portuguese regional tags → single `pt` bucket (matches app supported set).
    if lower in {"pt-br", "pt_br"} or lower.startswith("pt-br-"):
        return "pt"
    if lower in {"pt-pt", "pt_pt"} or lower.startswith("pt-pt-"):
        return "pt"

    primary = lower.split("-")[0]
    if primary in {"iw", "he"}:
        return "he"
    if primary in {"nb", "nn", "no"}:
        return "no"
    if primary in SUPPORTED_LOCALES:
        return primary
    return "en"


def is_rtl_locale(locale: str | None) -> bool:
    loc = normalize_locale(locale)
    if loc in {"ar", "he"}:
        return True
    primary = loc.split("-", 1)[0] if loc else ""
    return primary in {"ar", "he"}


def language_name(locale: str | None) -> str:
    loc = normalize_locale(locale)
    if loc == "uk":
        return "Ukrainian"
    if loc == "ru":
        return "Russian"
    if loc == "es":
        return "Spanish"
    if loc == "pt":
        return "Portuguese"
    if loc == "fr":
        return "French"
    if loc == "de":
        return "German"
    if loc == "it":
        return "Italian"
    if loc == "pl":
        return "Polish"
    if loc == "tr":
        return "Turkish"
    if loc == "zh":
        return "Chinese (Simplified)"
    if loc == "zh-TW":
        return "Chinese (Traditional)"
    if loc == "ja":
        return "Japanese"
    if loc == "ko":
        return "Korean"
    if loc == "hi":
        return "Hindi"
    if loc == "id":
        return "Indonesian"
    if loc == "vi":
        return "Vietnamese"
    if loc == "th":
        return "Thai"
    if loc == "ar":
        return "Arabic"
    if loc == "he":
        return "Hebrew"
    if loc == "nl":
        return "Dutch"
    if loc == "sv":
        return "Swedish"
    if loc == "cs":
        return "Czech"
    if loc == "ro":
        return "Romanian"
    if loc == "hu":
        return "Hungarian"
    if loc == "el":
        return "Greek"
    if loc == "da":
        return "Danish"
    if loc == "fi":
        return "Finnish"
    if loc == "no":
        return "Norwegian"
    return "English"

