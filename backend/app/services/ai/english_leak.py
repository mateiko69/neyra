"""Detect common English product phrases leaked into non-English AI/UI surfaces."""

from __future__ import annotations

from app.services.ai.ai_request_locale import normalize_ai_request_locale

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
    "coffee shop",
    "be honest",
    "wingman",
    "pick a vibe",
    "don't waste it",
    "dont waste it",
)


def english_leak_detected(text: str | None, *, locale: str | None) -> bool:
    if normalize_ai_request_locale(locale) == "en":
        return False
    t = (text or "").lower()
    return any(marker in t for marker in ENGLISH_LEAK_MARKERS)
