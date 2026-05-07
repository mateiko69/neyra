"""
Single source of truth for app locale codes: mirrors ``frontend/locales/*.json`` basenames.

Used by AI phrase banks, tests, and cache/locale validation.
"""

from __future__ import annotations

from pathlib import Path

# Frozen fallback when the repo layout has no ``frontend/locales`` (e.g. slim containers).
_FALLBACK_LOCALES: tuple[str, ...] = (
    "ar",
    "bg",
    "cs",
    "da",
    "de",
    "el",
    "en",
    "es",
    "fi",
    "fr",
    "he",
    "hi",
    "hu",
    "id",
    "it",
    "ja",
    "ko",
    "nl",
    "no",
    "pl",
    "pt",
    "ro",
    "ru",
    "sv",
    "th",
    "tr",
    "uk",
    "vi",
    "zh-CN",
    "zh-TW",
)


def _repo_root() -> Path:
    # backend/app/constants/supported_app_locales.py -> parents[3] == workspace root
    return Path(__file__).resolve().parents[3]


def discover_supported_app_locale_codes() -> tuple[str, ...]:
    loc_dir = _repo_root() / "frontend" / "locales"
    if not loc_dir.is_dir():
        return _FALLBACK_LOCALES
    codes = sorted({p.stem for p in loc_dir.glob("*.json") if p.suffix.lower() == ".json"})
    return tuple(codes) if codes else _FALLBACK_LOCALES


ALL_SUPPORTED_APP_LOCALES: tuple[str, ...] = discover_supported_app_locale_codes()

# Alias requested by product/docs (29-language AI localization).
ALL_SUPPORTED_LOCALES: tuple[str, ...] = ALL_SUPPORTED_APP_LOCALES
