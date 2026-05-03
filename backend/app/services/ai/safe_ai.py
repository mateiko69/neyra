"""
Centralized safe execution for AI endpoints — never leak provider crashes as bare 500/503.

Use ``safe_ai_generate_async`` / ``safe_ai_generate_sync`` to wrap provider calls and
return deterministic fallbacks while logging ``ai_fallback_triggered`` (at most once per
request for the same logical endpoint + provider; see ``log_ai_fallback_triggered``).
Dedupe is applied before ``fallback_fn`` runs so nested failures only emit
``gemini_suppressed_same_request`` after the first primary line.

When ``reraise=True``, failures are logged then the original exception is re-propagated
(so callers can handle or wrap at the HTTP boundary).
"""

from __future__ import annotations

import inspect
import logging
from collections.abc import Awaitable, Callable
from typing import TypeVar

from app.services.ai.ai_generation_context import (
    _dedupe_key_set,
    get_ai_action_id,
    get_ai_request_id,
)

logger = logging.getLogger("neyra.ai.safe")

T = TypeVar("T")


def _normalize_fallback_dedupe_endpoint(endpoint: str) -> str:
    """
    Map internal sub-calls to a single logical surface for dedupe, e.g. chat-brain tone + one_line
    should not emit two identical ``ai_fallback_triggered`` lines in one HTTP request.
    """
    ep = (endpoint or "").strip()
    if ep.startswith("chat-brain/"):
        return "chat-brain/suggestions"
    return ep


def _reason_from_exception(exc: BaseException) -> str:
    code = getattr(exc, "code", None)
    if code is not None and str(code).strip():
        return str(code).strip()[:120]
    return type(exc).__name__


def log_ai_fallback_triggered(
    *,
    endpoint: str,
    locale: str | None,
    reason: str,
    error_message: str,
    provider: str = "gemini",
    action_id: str | None = None,
) -> bool:
    """
    Emit at most one ``ai_fallback_triggered`` per (request_id, logical endpoint, provider)
    within the current HTTP request.

    Reason is included in the primary event payload only for that first failure.
    Additional failures for the same endpoint in the same request log
    ``gemini_suppressed_same_request`` (same logger) and return False.

    Returns True if the primary ``ai_fallback_triggered`` log was written; False otherwise.
    """
    rid = get_ai_request_id()
    dedupe_ep = _normalize_fallback_dedupe_endpoint(endpoint)
    rsn = (reason or "").strip()[:120]
    prov = (provider or "gemini").strip()[:64]
    key = (rid, dedupe_ep, prov)
    bucket = _dedupe_key_set()
    if key in bucket:
        logger.warning(
            "gemini_suppressed_same_request",
            extra={
                "event": "gemini_suppressed_same_request",
                "request_id": rid,
                "endpoint": endpoint,
                "dedupe_endpoint": dedupe_ep,
                "suppressed_reason": rsn,
                "provider": prov,
                "locale": (locale or "")[:24],
                "suppressed_error_message": (error_message or "")[:500],
            },
        )
        return False

    bucket.add(key)

    aid = (action_id or get_ai_action_id() or "").strip()[:80]
    logger.warning(
        "ai_fallback_triggered",
        extra={
            "event": "ai_fallback_triggered",
            "request_id": rid,
            "action_id": aid or None,
            "endpoint": endpoint,
            "dedupe_endpoint": dedupe_ep,
            "locale": (locale or "")[:24],
            "reason": rsn,
            "provider": prov,
            "error_message": (error_message or "")[:2000],
        },
    )
    return True


def safe_ai_generate_sync(
    generator_fn: Callable[[], T],
    fallback_fn: Callable[[], T] | None,
    *,
    endpoint: str,
    locale: str | None = None,
    provider: str = "gemini",
    reraise: bool = False,
) -> T:
    try:
        return generator_fn()
    except Exception as e:
        emitted = log_ai_fallback_triggered(
            endpoint=endpoint,
            locale=locale,
            reason=_reason_from_exception(e),
            error_message=str(e),
            provider=provider,
        )
        if reraise:
            raise
        if fallback_fn is None:
            raise RuntimeError("safe_ai_generate_sync: fallback_fn required when reraise=False") from e
        if emitted:
            try:
                from app.services.ai.gemini_client import log_ai_provider_final

                log_ai_provider_final(ai_provider_final="fallback", endpoint=endpoint, reason=_reason_from_exception(e))
            except Exception:
                pass
        return fallback_fn()


async def safe_ai_generate_async(
    generator_fn: Callable[[], Awaitable[T]],
    fallback_fn: Callable[[], T] | None,
    *,
    endpoint: str,
    locale: str | None = None,
    provider: str = "gemini",
    reraise: bool = False,
) -> T:
    try:
        return await generator_fn()
    except Exception as e:
        emitted = log_ai_fallback_triggered(
            endpoint=endpoint,
            locale=locale,
            reason=_reason_from_exception(e),
            error_message=str(e),
            provider=provider,
        )
        if reraise:
            raise
        if fallback_fn is None:
            raise RuntimeError("safe_ai_generate_async: fallback_fn required when reraise=False") from e
        if emitted:
            try:
                from app.services.ai.gemini_client import log_ai_provider_final

                log_ai_provider_final(ai_provider_final="fallback", endpoint=endpoint, reason=_reason_from_exception(e))
            except Exception:
                pass
        res = fallback_fn()
        if inspect.isawaitable(res):
            return await res  # type: ignore[misc]
        return res


def safe_ai_generate(
    request,
    generator_fn: Callable[[], T],
    fallback_fn: Callable[[], T] | None,
    *,
    endpoint: str = "",
    locale: str | None = None,
    provider: str = "gemini",
    reraise: bool = False,
) -> T:
    """
    Sync wrapper matching the product contract: ``request`` is accepted for API symmetry
    (logging context); execution is synchronous.
    """
    del request  # reserved for future request-scoped logging
    return safe_ai_generate_sync(
        generator_fn,
        fallback_fn,
        endpoint=endpoint or "unknown",
        locale=locale,
        provider=provider,
        reraise=reraise,
    )
