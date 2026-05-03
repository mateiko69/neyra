from __future__ import annotations

from app.services.ai.ai_request_locale import normalize_ai_request_locale, normalize_chat_ai_locale
from app.services.ai.output_script_locale import text_matches_requested_locale as _text_matches


def normalize_locale(locale: str | None) -> str:
    # Backwards compatible shim: delegate to localization locale normalizer.
    from app.services.localization.locale import normalize_locale as _norm

    return _norm(locale)


def is_text_locale(text: str, locale: str | None) -> bool:
    """Back-compat alias: script/locale heuristic for AI suggestion text."""
    return _text_matches(text, locale)


def ensure_locale(text: str, locale: str | None, fallback_by_locale: dict[str, str]) -> str:
    loc = normalize_ai_request_locale(locale)
    value = (text or "").strip()
    if value and _text_matches(value, loc):
        return value
    fb = (
        fallback_by_locale.get(loc)
        or fallback_by_locale.get(loc.split("-")[0] if "-" in loc else loc)
        or fallback_by_locale.get("en")
        or next(iter(fallback_by_locale.values()), "")
    )
    return (fb or "").strip()

