import json
import logging
import time

import redis
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from app.core.config import settings

log = logging.getLogger("neyra.ratelimit")


def _is_production_env() -> bool:
    return (settings.ENV or "").strip().lower() in ("production", "prod")


def _upload_public_prefix() -> str:
    p = (getattr(settings, "UPLOAD_PUBLIC_PREFIX", None) or f"/{settings.LOCAL_UPLOAD_DIR}").strip()
    return p if p.startswith("/") else f"/{p}"


def _should_skip_rate_limit(path: str, method: str) -> bool:
    """OPTIONS is never counted. In non-production, skip chatty / deterministic dev paths."""
    if method.upper() == "OPTIONS":
        return True
    # Public profile/media files: many parallel <img> requests must not trip the IP bucket.
    if method.upper() == "GET":
        up = _upload_public_prefix()
        if path == up or path.startswith(up + "/"):
            return True
    if _is_production_env():
        return False
    if path in ("/api/v1/analytics/track", "/api/v1/analytics/track/batch"):
        return True
    if path == "/api/v1/nav/badges":
        return True
    dev_prefixes = (
        "/api/v1/ai/readiness-score",
        "/api/v1/ai/coach",
        "/api/v1/ai/recovery",
        "/api/v1/ai/escalation-readiness",
    )
    return any(path == p or path.startswith(p + "/") for p in dev_prefixes)


class RateLimitMiddleware(BaseHTTPMiddleware):
    _client = None

    async def dispatch(self, request, call_next):
        if not settings.RATE_LIMIT_ENABLED:
            return await call_next(request)

        path = request.url.path
        method = request.method or ""
        if _should_skip_rate_limit(path, method):
            return await call_next(request)

        ip = request.client.host if request.client else "unknown"
        now = int(time.time())
        minute = now // 60

        try:
            if self._client is None:
                self._client = redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)
            key = f"rate:ip:{ip}:{minute}"
            count = self._client.incr(key)
            if count == 1:
                self._client.expire(key, 90)
            if count > settings.RATE_LIMIT_PER_MINUTE:
                if not _is_production_env():
                    log.warning(
                        json.dumps(
                            {
                                "event": "rate_limit_blocked",
                                "path": path,
                                "method": method,
                                "status": 429,
                                "rate_limit_key": key,
                                "count": count,
                                "limit": settings.RATE_LIMIT_PER_MINUTE,
                            }
                        )
                    )
                return JSONResponse(
                    status_code=429,
                    content={
                        "detail": "Rate limit exceeded",
                        "rate_limit_key": key,
                        "rate_limit_count": count,
                        "rate_limit_max": settings.RATE_LIMIT_PER_MINUTE,
                    },
                )
        except Exception:
            pass

        return await call_next(request)
