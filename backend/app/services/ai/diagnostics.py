from __future__ import annotations

import hashlib
import logging
from datetime import UTC, datetime
from threading import Lock
from typing import Any

from app.services.ai.cache import get_redis

log = logging.getLogger("neyra.ai.diagnostics")

_lock = Lock()
_last_provider_used: str | None = None
_last_gemini_error: str | None = None
_last_gemini_quota_error: str | None = None
_gemini_cooldown_until_ts: float | None = None
_gemini_cooldown_logged_ts: float | None = None

_GEMINI_COOLDOWN_KEY = "ai:gemini:cooldown_until_ts"
_GEMINI_COOLDOWN_LOG_KEY = "ai:gemini:cooldown_logged_ts"
_AI_PROVIDER_ERR_ZSET = "ai:provider_error_buckets:z"
_AI_PROVIDER_ERR_PREFIX = "ai:provider_error_bucket:"


def set_last_provider_used(value: str) -> None:
    global _last_provider_used
    with _lock:
        _last_provider_used = (value or "").strip() or None


def set_last_gemini_error(value: str | None) -> None:
    global _last_gemini_error
    with _lock:
        v = (value or "").strip()
        _last_gemini_error = v[:2000] if v else None


def clear_last_gemini_error() -> None:
    """Clear sticky provider error after a successful Gemini call (e.g. after model fallback)."""
    set_last_gemini_error(None)


def get_last_provider_used() -> str | None:
    with _lock:
        return _last_provider_used


def get_last_gemini_error() -> str | None:
    with _lock:
        return _last_gemini_error


def set_last_gemini_quota_error(value: str | None) -> None:
    global _last_gemini_quota_error
    with _lock:
        v = (value or "").strip()
        _last_gemini_quota_error = v[:4000] if v else None


def get_last_gemini_quota_error() -> str | None:
    with _lock:
        return _last_gemini_quota_error


def get_gemini_cooldown_until_ts() -> float | None:
    """Unix timestamp (seconds) when Gemini cooldown ends, or None."""
    try:
        r = get_redis()
        if r:
            raw = r.get(_GEMINI_COOLDOWN_KEY)
            return float(raw) if raw else None
    except Exception:
        pass
    with _lock:
        return _gemini_cooldown_until_ts


def set_gemini_cooldown(*, seconds: int, reason: str = "quota_exhausted") -> float:
    """Set provider cooldown window; returns unix timestamp until."""
    until = float(datetime.now(UTC).timestamp() + max(60, int(seconds)))
    try:
        r = get_redis()
        if r:
            r.set(_GEMINI_COOLDOWN_KEY, str(until), ex=max(120, int(seconds) + 60))
            return until
    except Exception:
        pass
    with _lock:
        global _gemini_cooldown_until_ts
        _gemini_cooldown_until_ts = until
    return until


def gemini_cooldown_active(now_ts: float | None = None) -> bool:
    now = float(now_ts if now_ts is not None else datetime.now(UTC).timestamp())
    until = get_gemini_cooldown_until_ts()
    return bool(until and until > now)


def ai_provider_operator_notice() -> str | None:
    """
    Short, non-alarming copy for admin/System Doctor when Gemini is in quota cooldown
    or recent errors look like rate limits — avoids repeating scary stack-like strings.
    """
    if gemini_cooldown_active():
        return "AI fallback active — Gemini cooling down"
    err = (get_last_gemini_error() or "").strip().lower()
    if not err:
        return None
    if any(x in err for x in ("429", "quota_exhausted", "resource_exhausted", "cooldown_active", "resource exhausted")):
        return "AI fallback active — Gemini cooling down"
    return None


def log_gemini_cooldown_active_once(*, cooldown_until_ts: float | None = None) -> None:
    """Log a single 'gemini_cooldown_active' per ~60s to avoid spam."""
    now = float(datetime.now(UTC).timestamp())
    until = float(cooldown_until_ts or get_gemini_cooldown_until_ts() or 0.0)
    if until <= now:
        return
    try:
        r = get_redis()
        if r:
            prev = r.get(_GEMINI_COOLDOWN_LOG_KEY)
            prev_ts = float(prev) if prev else 0.0
            if now - prev_ts < 60.0:
                return
            r.set(_GEMINI_COOLDOWN_LOG_KEY, str(now), ex=120)
            log.info("gemini_cooldown_active", extra={"event": "gemini_cooldown_active", "until_ts": until})
            return
    except Exception:
        pass
    with _lock:
        global _gemini_cooldown_logged_ts
        prev = float(_gemini_cooldown_logged_ts or 0.0)
        if now - prev < 60.0:
            return
        _gemini_cooldown_logged_ts = now
    log.info("gemini_cooldown_active", extra={"event": "gemini_cooldown_active", "until_ts": until})


def clear_gemini_cooldown() -> None:
    """Clear provider cooldown (tests/dev only)."""
    try:
        r = get_redis()
        if r:
            r.delete(_GEMINI_COOLDOWN_KEY)
            r.delete(_GEMINI_COOLDOWN_LOG_KEY)
    except Exception:
        pass
    with _lock:
        global _gemini_cooldown_until_ts, _gemini_cooldown_logged_ts
        _gemini_cooldown_until_ts = None
        _gemini_cooldown_logged_ts = None


def _utc_day_key(prefix: str) -> str:
    day = datetime.now(UTC).strftime("%Y%m%d")
    return f"{prefix}:{day}"


def _utc_minute_key(prefix: str) -> str:
    minute = datetime.now(UTC).strftime("%Y%m%d%H%M")
    return f"{prefix}:{minute}"


def incr_gemini_calls_today() -> int:
    try:
        r = get_redis()
        if not r:
            return 0
        key = _utc_day_key("ai:gemini:calls_day")
        n = int(r.incr(key))
        r.expire(key, 60 * 60 * 30)  # keep ~30h
        return n
    except Exception:
        return 0


def incr_gemini_calls_minute() -> int:
    try:
        r = get_redis()
        if not r:
            return 0
        key = _utc_minute_key("ai:gemini:calls_minute")
        n = int(r.incr(key))
        r.expire(key, 60 * 10)
        return n
    except Exception:
        return 0


def get_gemini_calls_today() -> int:
    try:
        r = get_redis()
        if not r:
            return 0
        raw = r.get(_utc_day_key("ai:gemini:calls_day"))
        return int(raw or 0)
    except Exception:
        return 0


def get_gemini_calls_minute() -> int:
    try:
        r = get_redis()
        if not r:
            return 0
        raw = r.get(_utc_minute_key("ai:gemini:calls_minute"))
        return int(raw or 0)
    except Exception:
        return 0


def incr_gemini_cache_hit() -> int:
    try:
        r = get_redis()
        if not r:
            return 0
        key = _utc_day_key("ai:gemini:cache_hit_day")
        n = int(r.incr(key))
        r.expire(key, 60 * 60 * 30)
        return n
    except Exception:
        return 0


def incr_gemini_cache_miss() -> int:
    try:
        r = get_redis()
        if not r:
            return 0
        key = _utc_day_key("ai:gemini:cache_miss_day")
        n = int(r.incr(key))
        r.expire(key, 60 * 60 * 30)
        return n
    except Exception:
        return 0


def get_gemini_cache_stats_today() -> dict:
    try:
        r = get_redis()
        if not r:
            return {"hits": 0, "misses": 0, "hit_rate": 0.0}
        hits = int(r.get(_utc_day_key("ai:gemini:cache_hit_day")) or 0)
        misses = int(r.get(_utc_day_key("ai:gemini:cache_miss_day")) or 0)
        den = hits + misses
        return {"hits": hits, "misses": misses, "hit_rate": (float(hits) / float(den) if den else 0.0)}
    except Exception:
        return {"hits": 0, "misses": 0, "hit_rate": 0.0}


def incr_fallback_24h() -> int:
    """
    Best-effort rolling 24h fallback counter (Redis key with 24h TTL).
    Never raises; returns 0 on failure.
    """
    try:
        r = get_redis()
        if not r:
            return 0
        key = "ai:fallback_count_24h"
        n = int(r.incr(key))
        # Refresh TTL each time to approximate rolling window.
        r.expire(key, 60 * 60 * 24)
        return n
    except Exception as e:
        log.debug("fallback_counter_failed err=%s", str(e))
        return 0


def get_fallback_count_24h() -> int:
    try:
        r = get_redis()
        if not r:
            return 0
        key = "ai:fallback_count_24h"
        raw = r.get(key)
        return int(raw or 0)
    except Exception:
        return 0


def incr_gemini_retry_scheduled() -> int:
    try:
        r = get_redis()
        if not r:
            return 0
        key = _utc_day_key("ai:gemini:retry_scheduled_day")
        n = int(r.incr(key))
        r.expire(key, 60 * 60 * 30)
        return n
    except Exception:
        return 0


def get_gemini_retry_scheduled_today() -> int:
    try:
        r = get_redis()
        if not r:
            return 0
        raw = r.get(_utc_day_key("ai:gemini:retry_scheduled_day"))
        return int(raw or 0)
    except Exception:
        return 0


def incr_gemini_success_day() -> int:
    try:
        r = get_redis()
        if not r:
            return 0
        key = _utc_day_key("ai:gemini:success_day")
        n = int(r.incr(key))
        r.expire(key, 60 * 60 * 30)
        return n
    except Exception:
        return 0


def incr_gemini_fail_day() -> int:
    try:
        r = get_redis()
        if not r:
            return 0
        key = _utc_day_key("ai:gemini:fail_day")
        n = int(r.incr(key))
        r.expire(key, 60 * 60 * 30)
        return n
    except Exception:
        return 0


def get_gemini_success_fail_today() -> dict[str, int]:
    try:
        r = get_redis()
        if not r:
            return {"success": 0, "fail": 0}
        ok = int(r.get(_utc_day_key("ai:gemini:success_day")) or 0)
        bad = int(r.get(_utc_day_key("ai:gemini:fail_day")) or 0)
        return {"success": ok, "fail": bad}
    except Exception:
        return {"success": 0, "fail": 0}


def record_ai_provider_error_bucket(*, provider: str, classification: str, endpoint: str) -> None:
    """Increment aggregated provider error bucket (Redis). Best-effort; never raises."""
    bkey = f"{(provider or '').strip()}|{(classification or '').strip()}|{(endpoint or '').strip()}"
    bucket_id = hashlib.sha256(bkey.encode("utf-8")).hexdigest()[:24]
    key = f"{_AI_PROVIDER_ERR_PREFIX}{bucket_id}"
    now = datetime.now(UTC).timestamp()
    now_iso = datetime.now(UTC).isoformat()
    try:
        r = get_redis()
        if not r:
            return
        pipe = r.pipeline()
        pipe.hincrby(key, "count", 1)
        pipe.hset(
            key,
            mapping={
                "provider": (provider or "").strip()[:64],
                "classification": (classification or "").strip()[:64],
                "endpoint": (endpoint or "").strip()[:128],
                "last_seen_iso": now_iso[:48],
            },
        )
        pipe.expire(key, 86400 * 14)
        pipe.zadd(_AI_PROVIDER_ERR_ZSET, {bucket_id: now})
        pipe.zremrangebyrank(_AI_PROVIDER_ERR_ZSET, 0, -101)
        pipe.execute()
    except Exception:
        pass


def get_recent_ai_provider_error_buckets(*, limit: int = 5) -> list[dict[str, Any]]:
    try:
        r = get_redis()
        if not r:
            return []
        lim = max(1, min(int(limit or 5), 25))
        ids = r.zrevrange(_AI_PROVIDER_ERR_ZSET, 0, lim - 1)
        out: list[dict[str, Any]] = []

        def _dec(v: object) -> str:
            return v.decode("utf-8", errors="ignore") if isinstance(v, bytes) else str(v or "")

        for bid in ids:
            bid_s = _dec(bid)
            raw = r.hgetall(f"{_AI_PROVIDER_ERR_PREFIX}{bid_s}")
            if not raw:
                continue
            m = {_dec(k): _dec(v) for k, v in raw.items()}
            try:
                cnt = int(m.get("count") or 0)
            except Exception:
                cnt = 0
            out.append(
                {
                    "provider": m.get("provider"),
                    "classification": m.get("classification"),
                    "endpoint": m.get("endpoint"),
                    "count": cnt,
                    "last_seen_iso": m.get("last_seen_iso"),
                    "message": None,
                }
            )
        return out
    except Exception:
        return []

