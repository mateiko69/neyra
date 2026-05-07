"""
Strict AI locale resolution + structured logging for observability.

Resolution order when ``ai_locale`` override is absent or ``auto``:

1. JSON body ``locale`` or ``language`` (combined by caller into ``request_locale``).
2. ``X-App-Locale`` header (canonical client UI locale transport).
3. Legacy UI headers ``X-Neyra-Locale`` / ``X-Locale`` / ``X-UI-Locale`` / ``locale`` query.
4. Profile ``preferred_language``.
5. ``Accept-Language``.
6. ``en``.
"""

from __future__ import annotations

import logging

from app.services.app_language import locale_from_accept_language_header
from app.services.ai.ai_request_locale import normalize_ai_request_locale
from app.services.ai.english_leak import english_leak_detected
from app.services.ai.locale import normalize_chat_ai_locale

logger = logging.getLogger("neyra.ai.locale_pipeline")

# Bump when Gemini / fallback prompt contracts change materially (scopes HTTP-level caches).
AI_PROMPT_VERSION = "neyra-ai-locale-v3"


def resolve_ai_locale_strict_chain(
    *,
    request_locale: str | None,
    app_locale_header: str | None,
    legacy_ui_locale: str | None,
    profile_locale: str | None,
    accept_language_header: str | None,
) -> tuple[str, str]:
    """
    Returns ``(normalized_locale, source_tag)``.
    ``source_tag`` is one of: request_body | x_app_locale | ui_header | profile | accept_language | fallback_en.
    """
    explicit = str(request_locale or "").strip()
    if explicit and explicit.lower() not in {"auto"}:
        return normalize_chat_ai_locale(explicit), "request_body"

    app_hdr = str(app_locale_header or "").strip()
    if app_hdr and app_hdr.lower() not in {"auto"}:
        return normalize_chat_ai_locale(app_hdr), "x_app_locale"

    legacy = str(legacy_ui_locale or "").strip()
    if legacy and legacy.lower() not in {"auto"}:
        return normalize_chat_ai_locale(legacy), "ui_header"

    prof = str(profile_locale or "").strip()
    if prof:
        return normalize_chat_ai_locale(prof), "profile"

    acc = locale_from_accept_language_header(accept_language_header)
    if acc:
        return normalize_chat_ai_locale(acc), "accept_language"

    return "en", "fallback_en"


def log_ai_locale_resolved(
    *,
    route: str,
    resolved_locale: str,
    resolution_source: str,
    req_locale_raw: str | None = None,
    profile_locale_raw: str | None = None,
    accept_language: str | None = None,
    transport_locale: str | None = None,
    ai_locale_override: str | None = None,
    prefer_message_locale: bool = False,
    message_locale_detected: str | None = None,
) -> None:
    logger.info(
        "ai_locale_resolved",
        extra={
            "event": "ai_locale_resolved",
            "route": (route or "")[:160],
            "resolved_locale": (resolved_locale or "")[:24],
            "resolution_source": (resolution_source or "")[:48],
            "request_locale": (str(req_locale_raw or "").strip()[:32] or None),
            "profile_locale": (str(profile_locale_raw or "").strip()[:32] or None),
            "accept_language": (str(accept_language or "").strip()[:240] or None),
            "transport_locale": (str(transport_locale or "").strip()[:32] or None),
            "ai_locale_override": (str(ai_locale_override or "").strip()[:24] or None),
            "prefer_message_locale": bool(prefer_message_locale),
            "message_locale_detected": (str(message_locale_detected or "").strip()[:24] or None),
        },
    )


def log_ai_response_debug(
    *,
    route: str,
    resolved_locale: str,
    profile_locale: str | None = None,
    request_locale: str | None = None,
    accept_language: str | None = None,
    final_language: str | None = None,
    fallback_used: bool = False,
    cache_hit: bool = False,
    output_language_guess: str | None = None,
    extra: dict | None = None,
) -> None:
    payload = {
        "event": "ai_response_debug",
        "route": (route or "")[:160],
        "resolved_locale": (resolved_locale or "")[:24],
        "profile_locale": (str(profile_locale or "").strip()[:32] or None),
        "request_locale": (str(request_locale or "").strip()[:32] or None),
        "accept_language": (str(accept_language or "").strip()[:240] or None),
        "final_language": (str(final_language or resolved_locale or "").strip()[:24] or None),
        "fallback_used": bool(fallback_used),
        "cache_hit": bool(cache_hit),
        "output_language_guess": (str(output_language_guess or "").strip()[:32] or None),
    }
    if extra:
        payload["extra"] = extra
    logger.info("ai_response_debug", extra=payload)


def log_ai_locale_final(
    *,
    route: str,
    locale: str,
    source: str,
    cache_hit: bool = False,
    fallback_used: bool = False,
    output_language_guess: str | None = None,
    output_snippet: str | None = None,
) -> None:
    loc = normalize_ai_request_locale(locale)
    leak_text = output_snippet or ""
    flagged = english_leak_detected(leak_text, locale=loc) if leak_text.strip() else False
    logger.info(
        "ai_locale_final",
        extra={
            "event": "ai_locale_final",
            "route": (route or "")[:160],
            "locale": (loc or "")[:24],
            "source": (source or "")[:48],
            "cache_hit": bool(cache_hit),
            "fallback_used": bool(fallback_used),
            "output_language_guess": (str(output_language_guess or "").strip()[:32] or None),
            "english_leak_detected": bool(flagged),
        },
    )
