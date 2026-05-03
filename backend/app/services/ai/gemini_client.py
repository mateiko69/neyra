from __future__ import annotations

import asyncio
import json
import logging
import random
import re
import time
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Literal

import httpx
from pydantic import BaseModel

from app.core.config import settings
from app.services.ai.gemini_global_gate import is_gemini_global_failure_cooldown_active, record_gemini_global_failure
from app.services.ai.providers.http_json import _extract_json
from app.services.ai.cache import cache_get, cache_key, cache_set
from app.services.ai.diagnostics import (
    clear_last_gemini_error,
    incr_gemini_calls_minute,
    incr_gemini_calls_today,
    incr_gemini_cache_hit,
    incr_gemini_cache_miss,
    incr_gemini_fail_day,
    incr_gemini_success_day,
    set_last_gemini_quota_error,
    gemini_cooldown_active,
    log_gemini_cooldown_active_once,
    set_gemini_cooldown,
)
from app.services.ai.diagnostics import set_last_gemini_error, set_last_provider_used

log = logging.getLogger("neyra.ai.gemini")

# Prevent httpx/httpcore from INFO-logging full request URLs (may include ?key=).
for _lg_name in ("httpx", "httpcore"):
    _hl = logging.getLogger(_lg_name)
    if _hl.level < logging.WARNING:
        _hl.setLevel(logging.WARNING)


def redact_gemini_log_text(text: str | None) -> str:
    """Strip API key material from arbitrary log lines (defense in depth)."""
    if not text:
        return ""
    s = str(text)
    try:
        import re as _re

        s = _re.sub(r"(?i)(key|api_key|token)=([^&\s]+)", r"\1=***", s)
        s = _re.sub(r"(AIza[0-9A-Za-z\-_]{20,})", "***", s)
    except Exception:
        pass
    return s

_MODEL_RE = re.compile(r"^[a-zA-Z0-9._-]+$")

# Single supported REST model for generateContent (env overrides are ignored for reliability).
_CANONICAL_GEMINI_MODEL = "gemini-2.5-flash-lite"

# After any Gemini HTTP failure in the current request scope, skip further Gemini calls (fallback paths only).
_gemini_failed_this_request: ContextVar[bool] = ContextVar("gemini_failed_this_request", default=False)
# At most one upstream HTTP POST per incoming HTTP request (cache hits do not count).
_gemini_upstream_posts_this_request: ContextVar[int] = ContextVar("gemini_upstream_posts_this_request", default=0)


def _resolved_allowed_surfaces() -> frozenset[str]:
    raw = (getattr(settings, "GEMINI_ALLOWED_SURFACES", "") or "").strip()
    if raw:
        return frozenset(x.strip() for x in raw.split(",") if x.strip())
    return frozenset(
        {
            "chat-brain",
            "timed-replies",
            "chat-copilot",
            "admin-debug",
            "timing-engine",
            "gemini-provider",
        }
    )


def reset_gemini_request_scope() -> None:
    """Call once per HTTP request (see main middleware) so parallel Gemini calls can share scope."""
    _gemini_failed_this_request.set(False)
    _gemini_upstream_posts_this_request.set(0)


def mark_gemini_request_failed() -> None:
    _gemini_failed_this_request.set(True)


def is_gemini_suppressed_after_failure() -> bool:
    return bool(_gemini_failed_this_request.get())


def log_ai_provider_final(*, ai_provider_final: Literal["gemini", "fallback"], **extra: Any) -> None:
    """Structured log for which provider satisfied the user-facing AI outcome."""
    log.info(
        "ai_provider_final",
        extra={"event": "ai_provider_final", "ai_provider_final": ai_provider_final, **extra},
    )


@dataclass(frozen=True)
class GeminiError(Exception):
    code: str
    message: str
    status_code: int | None = None
    response_body: str | None = None
    provider: str = "gemini"
    model: str = ""
    retryable: bool = False


def _gemini_error_should_retry(e: GeminiError) -> bool:
    """One follow-up attempt on transient upstream / transport failures."""
    if getattr(e, "retryable", False):
        return True
    code = e.code or ""
    if code in {"timeout", "upstream_unavailable", "quota_exhausted"}:
        return True
    sc = e.status_code
    if sc is not None and sc in {408, 429, 500, 502, 503, 504}:
        return True
    return False


class GeminiClient:
    """Gemini REST client for ``generateContent`` with one optional retry on transient errors.

    Never raises raw httpx exceptions to callers.
    """

    def __init__(self, http_client: httpx.AsyncClient | None = None):
        self._client = http_client or httpx.AsyncClient()

    @staticmethod
    def enabled() -> bool:
        return bool((settings.GEMINI_API_KEY or "").strip())

    @staticmethod
    def model_chain() -> list[str]:
        """Single stable model ID (see ``_CANONICAL_GEMINI_MODEL``)."""
        return [_CANONICAL_GEMINI_MODEL]

    @staticmethod
    def normalize_model_id(model: str | None) -> str:
        """
        Accept both raw IDs like 'gemini-2.5-flash' and prefixed IDs like 'models/gemini-2.5-flash'.
        Returns the canonical raw ID (no 'models/' prefix).
        """
        m = (model or "").strip()
        if not m:
            return ""
        if m.startswith("models/"):
            return m.split("models/", 1)[1].strip()
        return m

    @staticmethod
    def model_name() -> str:
        return GeminiClient.model_chain()[0]

    @staticmethod
    def _validate_model(model: str) -> str | None:
        m = GeminiClient.normalize_model_id(model)
        if not m:
            return "Model is empty."
        if not _MODEL_RE.match(m):
            return "Model contains invalid characters."
        return None

    async def generate_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        out_model: type[BaseModel] | None = None,
        timeout_s: float = 10.0,
        max_retries: int = 1,
        temperature: float | None = None,
        max_output_tokens: int | None = None,
        model: str | None = None,
        surface: str | None = None,
    ) -> BaseModel:
        """
        Calls Gemini ``generateContent``. After the first failure on transient errors (5xx, 408, 429,
        timeout, …), retries once when ``max_retries`` >= 1 (default).

        The REST model is always ``gemini-2.5-flash-lite``; the ``model`` argument is logged if it differs.
        Pass ``surface`` (e.g. chat-copilot) when GEMINI_PRIORITY_SURFACES_ONLY is enabled.
        """
        requested = self.normalize_model_id(model)
        if requested and requested != _CANONICAL_GEMINI_MODEL:
            log.info(
                "gemini_model_override_ignored",
                extra={
                    "event": "gemini_model_override_ignored",
                    "requested_model": requested,
                    "model_used": _CANONICAL_GEMINI_MODEL,
                },
            )
        model_id = _CANONICAL_GEMINI_MODEL
        primary_label = _CANONICAL_GEMINI_MODEL

        if not self.enabled():
            err = GeminiError(
                code="missing_api_key",
                message="Gemini API key is missing.",
                status_code=None,
                model=primary_label,
                retryable=False,
            )
            _log_gemini_error(err, persist=True)
            raise err

        if bool(getattr(settings, "GEMINI_PRIORITY_SURFACES_ONLY", False)):
            allowed = _resolved_allowed_surfaces()
            surf = (surface or "").strip()
            if surf not in allowed:
                err = GeminiError(
                    code="gemini_surface_not_allowed",
                    message=f"Gemini surface '{surf or 'unset'}' is not in the allowed set for this deployment.",
                    status_code=None,
                    model=primary_label,
                    retryable=False,
                )
                log.warning(
                    "gemini_surface_blocked",
                    extra={"ai_provider": "gemini", "surface": surf or None, "allowed": sorted(allowed)},
                )
                raise err

        def _url_for(m: str) -> str:
            mid = self.normalize_model_id(m)
            return f"https://generativelanguage.googleapis.com/v1/models/{mid}:generateContent"

        def _safe_url_for_log(m: str) -> str:
            return f"{_url_for(m)}?key=***"

        params = {"key": settings.GEMINI_API_KEY}

        safety_prefix = (
            "Safety rules (must follow):\n"
            "- Do NOT generate sexual explicit content.\n"
            "- Do NOT generate harassment/hate.\n"
            "- Do NOT provide creepy/manipulative dating advice.\n"
            "- Keep tone respectful, natural, and consent-forward.\n"
        )

        prompt_text = f"{safety_prefix}\n{system_prompt}\n\n{user_prompt}"
        payload: dict[str, Any] = {
            "contents": [
                {
                    "parts": [{"text": prompt_text}],
                }
            ],
            "generationConfig": {
                "temperature": float(settings.AI_TEMPERATURE if temperature is None else temperature),
                "maxOutputTokens": int(max_output_tokens or settings.AI_MAX_TOKENS),
            },
        }

        model = self.normalize_model_id(model_id)
        invalid_reason = self._validate_model(model)
        if invalid_reason:
            log.warning(
                "gemini_skip_invalid_model",
                extra={"model": model, "reason": invalid_reason},
            )
            err = GeminiError(
                code="invalid_model",
                message=invalid_reason,
                status_code=None,
                model=primary_label,
                retryable=False,
            )
            incr_gemini_fail_day()
            _log_gemini_error(err, persist=True)
            raise err

        cache_payload = {
            "provider": "gemini",
            "model": model,
            "prompt": prompt_text,
            "generation": payload.get("generationConfig") or {},
        }
        ck = cache_key("gemini_prompt_v1", cache_payload)
        cached = cache_get(ck)
        if isinstance(cached, dict):
            incr_gemini_cache_hit()
            set_last_provider_used("gemini")
            clear_last_gemini_error()
            incr_gemini_success_day()
            log_ai_provider_final(ai_provider_final="gemini", ai_model=model, source="cache")
            if out_model is None:
                return cached
            return out_model.model_validate(cached)
        incr_gemini_cache_miss()

        if is_gemini_suppressed_after_failure():
            err = GeminiError(
                code="same_request_gemini_suppressed",
                message="Gemini already failed in this request; skipping further Gemini calls.",
                status_code=None,
                model=primary_label,
                retryable=False,
            )
            log.warning(
                "gemini_suppressed_same_request",
                extra={"ai_provider": "gemini", "ai_model": primary_label, "code": err.code},
            )
            raise err

        if is_gemini_global_failure_cooldown_active():
            log.warning(
                "gemini_skip_global_cooldown",
                extra={
                    "event": "gemini_skip_global_cooldown",
                    "gemini_skipped_due_to_cooldown": True,
                    "ai_provider": "gemini",
                    "ai_model": model,
                    "surface": (surface or "")[:64] or None,
                },
            )
            raise GeminiError(
                code="global_failure_cooldown",
                message="Gemini temporarily unavailable after a recent failure (cooldown).",
                status_code=None,
                model=model,
                retryable=False,
            )

        # Provider cooldown from upstream 429/quota (distinct from globalFailureCooldown).
        if gemini_cooldown_active():
            log_gemini_cooldown_active_once()
            raise GeminiError(
                code="cooldown_active",
                message="Gemini cooldown active",
                status_code=429,
                model=primary_label,
                retryable=False,
            )

        cur_posts = int(_gemini_upstream_posts_this_request.get() or 0)
        if cur_posts >= 1:
            err = GeminiError(
                code="gemini_single_upstream_per_http_request",
                message="Only one Gemini upstream call per HTTP request is allowed.",
                status_code=None,
                model=primary_label,
                retryable=False,
            )
            log.warning(
                "gemini_suppressed_second_upstream",
                extra={"ai_provider": "gemini", "ai_model": primary_label, "code": err.code, "surface": (surface or "")[:64] or None},
            )
            raise err
        _gemini_upstream_posts_this_request.set(cur_posts + 1)

        max_attempts = 1 + max(0, int(max_retries))
        _body_cap = 8000

        for attempt in range(1, max_attempts + 1):
            t0 = time.time()
            log.info(
                "ai_request_started",
                extra={
                    "ai_provider": "gemini",
                    "ai_model": model,
                    "attempt": attempt,
                    "max_attempts": max_attempts,
                    "timeout_s": timeout_s,
                    "surface": (surface or "")[:64] or None,
                },
            )
            try:
                log.info(
                    "gemini_payload_meta",
                    extra={
                        "event": "gemini_payload_meta",
                        "model": model,
                        "prompt_chars": len(prompt_text),
                        "temperature": (payload.get("generationConfig") or {}).get("temperature"),
                        "maxOutputTokens": (payload.get("generationConfig") or {}).get("maxOutputTokens"),
                    },
                )
                log.info(
                    "gemini_request",
                    extra={"event": "gemini_request", "url": _safe_url_for_log(model), "model": model},
                )
                incr_gemini_calls_today()
                incr_gemini_calls_minute()
                resp = await self._client.post(
                    _url_for(model),
                    params=params,
                    json=payload,
                    headers={"Content-Type": "application/json"},
                    timeout=timeout_s,
                )
                status = int(resp.status_code)
                if status >= 500 or status in {408, 429}:
                    if status == 429:
                        set_last_gemini_quota_error((resp.text or "")[:1200])
                        try:
                            seconds = int(random.randint(5 * 60, 15 * 60))
                        except Exception:
                            seconds = 8 * 60
                        until_ts = set_gemini_cooldown(seconds=seconds, reason="quota_exhausted")
                        log_gemini_cooldown_active_once(cooldown_until_ts=until_ts)
                    raise GeminiError(
                        code="quota_exhausted" if status == 429 else "upstream_unavailable",
                        message=f"Gemini upstream returned {status}",
                        status_code=status,
                        response_body=(resp.text or "")[:_body_cap],
                        model=model,
                        retryable=True,
                    )
                if status >= 400:
                    msg = ""
                    try:
                        js = resp.json()
                        msg = str(js.get("error", {}).get("message") or js.get("message") or "")
                    except Exception:
                        msg = (resp.text or "").strip()
                    msg = (msg or f"Gemini request failed ({status})").strip()
                    ml = msg.lower()
                    is_quota_like = status == 429 or (status == 403 and any(x in ml for x in ("quota", "resource", "exhausted")))
                    if is_quota_like:
                        set_last_gemini_quota_error((resp.text or msg)[:1200])
                        try:
                            seconds = int(random.randint(5 * 60, 15 * 60))
                        except Exception:
                            seconds = 8 * 60
                        until_ts = set_gemini_cooldown(seconds=seconds, reason="quota_exhausted")
                        log_gemini_cooldown_active_once(cooldown_until_ts=until_ts)
                    elif status == 403:
                        set_last_gemini_quota_error(None)
                    err_code = "bad_request"
                    if status == 403 and not is_quota_like:
                        err_code = "provider_forbidden"
                    elif status in {403, 429} and is_quota_like:
                        err_code = "quota_exhausted"
                    q_retry = err_code == "quota_exhausted" or status == 429
                    raise GeminiError(
                        code=err_code,
                        message=msg[:500],
                        status_code=status,
                        response_body=(resp.text or "")[:_body_cap],
                        model=model,
                        retryable=bool(q_retry),
                    )

                data = resp.json()
                if str(getattr(settings, "ENV", "") or "").strip().lower() == "development" and out_model is None:
                    set_last_provider_used("gemini")
                    clear_last_gemini_error()
                    incr_gemini_success_day()
                    log_ai_provider_final(ai_provider_final="gemini", ai_model=model, source="response")
                    return data

                text = (
                    (((data.get("candidates") or [{}])[0].get("content") or {}).get("parts") or [{}])[0].get("text")
                    or ""
                )
                try:
                    extracted = _extract_json(text)
                    parsed = json.loads(extracted)
                except Exception as parse_exc:
                    raise GeminiError(
                        code="parse_error",
                        message=f"Gemini response could not be parsed: {parse_exc}",
                        status_code=status,
                        response_body=(text or "")[:_body_cap],
                        model=model,
                        retryable=False,
                    )
                cache_set(ck, parsed, ttl_seconds=60 * 10)
                out = out_model.model_validate(parsed) if out_model is not None else parsed
                set_last_provider_used("gemini")
                clear_last_gemini_error()
                log.info(
                    "ai_request_success",
                    extra={
                        "ai_provider": "gemini",
                        "ai_model": model,
                        "attempt": attempt,
                        "elapsed_ms": int((time.time() - t0) * 1000),
                    },
                )
                log_ai_provider_final(ai_provider_final="gemini", ai_model=model, source="response")
                incr_gemini_success_day()
                return out
            except GeminiError as e:
                if attempt < max_attempts and _gemini_error_should_retry(e):
                    _log_gemini_error(e, persist=False)
                    log.warning(
                        "gemini_retry",
                        extra={
                            "event": "gemini_retry",
                            "ai_provider": "gemini",
                            "ai_model": model,
                            "attempt": attempt,
                            "max_attempts": max_attempts,
                            "code": e.code,
                            "status_code": e.status_code,
                        },
                    )
                    await asyncio.sleep(min(0.2 * attempt, 1.5))
                    continue
                mark_gemini_request_failed()
                record_gemini_global_failure()
                log.warning(
                    "ai_request_failed",
                    extra={
                        "ai_provider": "gemini",
                        "ai_model": model,
                        "attempt": attempt,
                        "code": e.code,
                        "status_code": e.status_code,
                        "retryable": getattr(e, "retryable", False),
                    },
                )
                incr_gemini_fail_day()
                _log_gemini_error(e, persist=True)
                raise
            except (httpx.TimeoutException, httpx.NetworkError) as e:
                net_err = GeminiError(
                    code="timeout",
                    message="Gemini request timed out or network error.",
                    status_code=None,
                    model=model,
                    retryable=True,
                )
                if attempt < max_attempts:
                    _log_gemini_error(net_err, persist=False)
                    log.warning(
                        "gemini_retry",
                        extra={
                            "event": "gemini_retry",
                            "ai_provider": "gemini",
                            "ai_model": model,
                            "attempt": attempt,
                            "max_attempts": max_attempts,
                            "code": "timeout",
                        },
                    )
                    await asyncio.sleep(min(0.2 * attempt, 1.5))
                    continue
                mark_gemini_request_failed()
                record_gemini_global_failure()
                log.warning(
                    "ai_request_failed",
                    extra={
                        "ai_provider": "gemini",
                        "ai_model": model,
                        "attempt": attempt,
                        "code": "timeout",
                        "retryable": True,
                    },
                )
                incr_gemini_fail_day()
                _log_gemini_error(net_err, persist=True)
                raise net_err from e
            except Exception as e:
                mark_gemini_request_failed()
                record_gemini_global_failure()
                last_err = GeminiError(
                    code="parse_error",
                    message="Gemini response could not be parsed.",
                    status_code=None,
                    model=model,
                    retryable=False,
                )
                log.exception(
                    "ai_request_failed",
                    extra={
                        "ai_provider": "gemini",
                        "ai_model": model,
                        "attempt": attempt,
                        "code": "parse_error",
                        "retryable": False,
                    },
                )
                incr_gemini_fail_day()
                _log_gemini_error(last_err, persist=True)
                raise last_err from e


def _log_gemini_error(e: GeminiError, *, persist: bool = True) -> None:
    """
    Full diagnostics for Gemini failures (no API key leakage).
    When persist=False, logs only — used before rotating to another model.
    """
    try:
        set_last_provider_used("gemini")
        if persist:
            set_last_gemini_error(f"{e.code}: {e.message}")
            try:
                from app.services.ai.diagnostics import record_ai_provider_error_bucket
                from app.services.ai.health_snapshot import classify_gemini_error

                cls = classify_gemini_error(f"{e.code}: {e.message}")
                record_ai_provider_error_bucket(provider="gemini", classification=cls, endpoint="generateContent")
            except Exception:
                pass
        rb = redact_gemini_log_text((e.response_body or "")[:8000]) if e.response_body else ""
        log_method = log.error if persist else log.warning
        log_method(
            "gemini_error" if persist else "gemini_error_transient",
            extra={
                "event": "gemini_error" if persist else "gemini_error_transient",
                "error": str(e.message or ""),
                "type": type(e).__name__,
                "status_code": e.status_code,
                "http_status": e.status_code,
                "response_body": rb if rb else None,
                "model_used": str(e.model or ""),
                "model": str(e.model or ""),
                "provider": "gemini",
                "code": str(e.code or ""),
                "persist": persist,
            },
        )
    except Exception:
        pass

