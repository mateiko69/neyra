"""
Strict AI locale resolution + structured logging for observability.

Resolution order (when ``ai_locale`` is absent or ``auto``):

1. Explicit JSON body ``locale`` / ``language`` field (caller passes ``req_locale``)
2. Authenticated viewer profile ``preferred_language``
3. ``Accept-Language`` header
4. UI transport headers (``X-Neyra-Locale``, ``X-Locale``, ``X-UI-Locale``, ``locale`` query)
5. ``en``
"""

from __future__ import annotations

import logging

from app.services.app_language import locale_from_accept_language_header
from app.services.ai.locale import normalize_chat_ai_locale

logger = logging.getLogger("neyra.ai.locale_pipeline")


def resolve_ai_locale_strict_chain(
    *,
    req_locale: str | None,
    profile_locale: str | None,
    accept_language_header: str | None,
    transport_locale: str | None,
) -> tuple[str, str]:
    """
    Returns ``(normalized_locale, source_tag)``.
    ``source_tag`` is one of: request_body | profile | accept_language | ui_header | fallback_en.
    """
    explicit = str(req_locale or "").strip()
    if explicit:
        return normalize_chat_ai_locale(explicit), "request_body"

    prof = str(profile_locale or "").strip()
    if prof:
        return normalize_chat_ai_locale(prof), "profile"

    acc = locale_from_accept_language_header(accept_language_header)
    if acc:
        return normalize_chat_ai_locale(acc), "accept_language"

    trans = str(transport_locale or "").strip()
    if trans:
        return normalize_chat_ai_locale(trans), "ui_header"

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
    }
    if extra:
        payload["extra"] = extra
    logger.info("ai_response_debug", extra=payload)
