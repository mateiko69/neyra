from __future__ import annotations

import logging


def log_ai_locale_context(
    logger: logging.Logger,
    *,
    endpoint: str,
    ui_locale: str | None,
    ai_locale: str,
    language_hint: str | None = None,
    source: str | None = None,
    fallback_used: bool | None = None,
    extra: dict | None = None,
) -> None:
    """Structured log: raw UI tag vs normalized AI locale (preserve zh-TW, etc.)."""
    payload = {
        "event": "ai_locale_context",
        "endpoint": endpoint,
        "requested_locale": (ui_locale or "").strip() or None,
        "normalized_locale": ai_locale,
        "ui_locale_raw": (ui_locale or "").strip() or None,
        "ai_locale_normalized": ai_locale,
        "language_hint": (language_hint or "").strip() or None,
    }
    if source is not None:
        payload["source"] = source
    if fallback_used is not None:
        payload["fallback_used"] = fallback_used
    if extra:
        payload.update(extra)
    logger.info("ai_locale_context", extra=payload)


def log_ai_locale_result(
    logger: logging.Logger,
    *,
    endpoint: str,
    requested_locale: str | None,
    normalized_locale: str,
    returned_language: str,
    fallback_used: bool,
    cache_hit: bool = False,
    source: str | None = None,
) -> None:
    logger.info(
        "ai_locale_result",
        extra={
            "event": "ai_locale_result",
            "endpoint": endpoint,
            "requested_locale": (requested_locale or "").strip() or None,
            "normalized_locale": normalized_locale,
            "returned_language": returned_language,
            "fallback_used": fallback_used,
            "cache_hit": cache_hit,
            "source": source,
        },
    )
