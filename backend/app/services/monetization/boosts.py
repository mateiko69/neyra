from __future__ import annotations

from app.services.ai.cache import get_redis

BOOST_TTL_SECONDS = 30 * 60


def _key(user_id: int) -> str:
    return f"boost:active:{int(user_id)}"


def activate_boost(user_id: int) -> bool:
    """Best-effort boost activation (Redis-backed). Returns True if stored."""
    try:
        r = get_redis()
    except Exception:
        return False
    try:
        r.set(_key(int(user_id)), "1", ex=BOOST_TTL_SECONDS)
        return True
    except Exception:
        return False


def is_boost_active(user_id: int) -> bool:
    try:
        r = get_redis()
    except Exception:
        return False
    try:
        v = r.get(_key(int(user_id)))
        return bool(v)
    except Exception:
        return False

