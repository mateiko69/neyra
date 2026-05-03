"""Per-request context for AI logging (request id, optional action id, fallback dedupe set)."""

from __future__ import annotations

import uuid
from contextvars import ContextVar

_ai_request_id: ContextVar[str] = ContextVar("ai_request_id", default="")
_ai_action_id: ContextVar[str] = ContextVar("ai_action_id", default="")
_ai_fallback_dedupe_keys: ContextVar[set[tuple[str, str, str]] | None] = ContextVar("ai_fallback_dedupe_keys", default=None)


def reset_ai_generation_log_context() -> None:
    """Call once at the start of each HTTP request (see ``main.py`` middleware)."""
    _ai_request_id.set(str(uuid.uuid4()))
    _ai_action_id.set("")
    _ai_fallback_dedupe_keys.set(set())


def get_ai_request_id() -> str:
    return _ai_request_id.get() or ""


def get_ai_action_id() -> str:
    return _ai_action_id.get() or ""


def set_ai_action_id(action_id: str | None) -> None:
    """Optional sub-scope within a request (debugging); included in log payload only."""
    _ai_action_id.set((action_id or "").strip())


def _dedupe_key_set() -> set[tuple[str, str, str]]:
    s = _ai_fallback_dedupe_keys.get()
    if s is None:
        s = set()
        _ai_fallback_dedupe_keys.set(s)
    return s
