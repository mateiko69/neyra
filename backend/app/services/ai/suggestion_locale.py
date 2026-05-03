"""Ensure AI suggestion lists match the requested UI locale (no English leakage)."""

from __future__ import annotations

from app.services.ai.ai_request_locale import normalize_ai_request_locale
from app.services.ai.centralized import fallback_reply_triplet
from app.services.ai.output_script_locale import text_matches_requested_locale


def ensure_suggestions_locale(suggestions: list[str], *, locale: str | None) -> list[str]:
    loc = normalize_ai_request_locale(locale or "en")
    if loc == "en":
        return suggestions
    clean = [str(x or "").strip() for x in suggestions if str(x or "").strip()]
    if not clean:
        return fallback_reply_triplet(locale=loc)
    ok = sum(1 for x in clean if text_matches_requested_locale(x, loc))
    if ok >= max(1, (len(clean) + 1) // 2):
        return suggestions
    return fallback_reply_triplet(locale=loc)
