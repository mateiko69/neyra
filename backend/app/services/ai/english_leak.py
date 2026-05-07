"""Detect common English product phrases leaked into non-English AI/UI surfaces."""

from __future__ import annotations

import logging

from app.services.ai.ai_request_locale import normalize_ai_request_locale

logger = logging.getLogger("neyra.ai.english_leak")

# Lowercase probes — avoid overly generic tokens (“nice ” alone).
ENGLISH_LEAK_MARKERS = (
    "start the conversation",
    "best option",
    "they're waiting",
    "theyre waiting",
    "ai match:",
    "ai match ",
    " ai match",
    "i'm curious",
    "im curious",
    "what made you",
    "what made you think",
    "coffee shop",
    "busy city",
    "be honest",
    "wingman",
    "pick a vibe",
    "don't waste it",
    "dont waste it",
    "that's a nice detail",
    "that’s a nice detail",
    "other options",
    "nice detail",
)


def english_leak_detected(text: str | None, *, locale: str | None) -> bool:
    if normalize_ai_request_locale(locale) == "en":
        return False
    t = (text or "").lower()
    return any(marker in t for marker in ENGLISH_LEAK_MARKERS)


def log_ai_english_leak_blocked(*, locale: str, surface: str, snippet: str | None = None) -> None:
    """Structured log when a non-English surface would have shipped English-ish copy."""
    logger.warning(
        "ai_english_leak_blocked",
        extra={
            "event": "ai_english_leak_blocked",
            "locale": (locale or "")[:24],
            "surface": (surface or "")[:160],
            "snippet": (snippet or "")[:240] if snippet else None,
        },
    )
