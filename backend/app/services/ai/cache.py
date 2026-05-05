from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

import redis

from app.core.config import settings

logger = logging.getLogger("neyra.ai.redis")
_redis_warned = False


def cache_key(prefix: str, payload: dict) -> str:
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    h = hashlib.sha256(raw).hexdigest()
    return f"ai:{prefix}:{h}"


def get_redis() -> redis.Redis:
    global _redis_warned
    if not (settings.REDIS_URL or "").strip():
        if not _redis_warned:
            _redis_warned = True
            logger.warning("redis_unavailable_using_local_fallback")
        raise RuntimeError("Redis disabled")
    try:
        return redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)
    except Exception:
        if not _redis_warned:
            _redis_warned = True
            logger.warning("redis_unavailable_using_local_fallback")
        raise


def cache_get(key: str) -> Any | None:
    try:
        r = get_redis()
        v = r.get(key)
        return json.loads(v) if v else None
    except Exception:
        return None


def cache_set(key: str, value: Any, ttl_seconds: int) -> None:
    try:
        r = get_redis()
        r.set(key, json.dumps(value, ensure_ascii=False), ex=int(ttl_seconds))
    except Exception:
        return


def get_user_cache_version(prefix: str, user_id: int) -> int:
    """Best-effort per-user cache version (Redis). Returns 0 if unavailable."""
    try:
        if not user_id:
            return 0
        r = get_redis()
        key = f"{prefix}:v:{int(user_id)}"
        v = r.get(key)
        return int(v or 0)
    except Exception:
        return 0


def bump_user_cache_version(prefix: str, user_id: int) -> int:
    """Increment per-user cache version (Redis). Returns next version or 0 if unavailable."""
    try:
        if not user_id:
            return 0
        r = get_redis()
        key = f"{prefix}:v:{int(user_id)}"
        return int(r.incr(key) or 0)
    except Exception:
        return 0

