"""
Cross-request Gemini backoff: after any upstream failure, suppress new Gemini HTTP calls
for GEMINI_GLOBAL_FAILURE_COOLDOWN_SECONDS (memory + optional Redis).
"""

from __future__ import annotations

import time

from app.core.config import settings

REDIS_KEY = "neyra:gemini:last_failure_epoch"

_mem_last_failure_ts: float = 0.0


def _cooldown_sec() -> float:
    try:
        return max(5.0, float(getattr(settings, "GEMINI_GLOBAL_FAILURE_COOLDOWN_SECONDS", 60) or 60))
    except Exception:
        return 60.0


def record_gemini_global_failure() -> None:
    """Call after any Gemini HTTP failure (shared across workers via Redis when available)."""
    global _mem_last_failure_ts
    ts = time.time()
    _mem_last_failure_ts = ts
    try:
        from app.services.ai.cache import get_redis

        r = get_redis()
        r.set(REDIS_KEY, str(ts), ex=int(_cooldown_sec()) + 60)
    except Exception:
        pass


def reset_gemini_global_failure_memory() -> None:
    """Process-local reset (tests / admin tooling). Redis key expires via TTL."""
    global _mem_last_failure_ts
    _mem_last_failure_ts = 0.0
    try:
        from app.services.ai.cache import get_redis

        get_redis().delete(REDIS_KEY)
    except Exception:
        pass


def is_gemini_global_failure_cooldown_active(*, now: float | None = None) -> bool:
    t = float(now if now is not None else time.time())
    if t - float(_mem_last_failure_ts or 0.0) < _cooldown_sec():
        return True
    try:
        from app.services.ai.cache import get_redis

        r = get_redis()
        raw = r.get(REDIS_KEY)
        if raw:
            ts = float(raw)
            return t - ts < _cooldown_sec()
    except Exception:
        pass
    return False
