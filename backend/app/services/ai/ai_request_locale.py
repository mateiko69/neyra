from __future__ import annotations

from app.services.localization.locale import normalize_locale as _normalize_app_locale


def normalize_ai_request_locale(locale: str | None) -> str:
    """Normalize to canonical app locale codes (matches frontend `AppLocale`, e.g. zh-TW)."""
    raw = (locale or "").strip()
    if not raw:
        return "en"
    return _normalize_app_locale(raw)


def normalize_chat_ai_locale(locale: str | None) -> str:
    """Chat AI surfaces: always honor UI locale tag (full supported set, no legacy allow-lists)."""
    return normalize_ai_request_locale(locale)
