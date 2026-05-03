"""
AI operational snapshot for System Doctor / alerts: degraded vs fail when Gemini misbehaves but fallback protects users.
"""

from __future__ import annotations

import hashlib
import time
from typing import Any

from app.core.config import settings
from app.services.ai.diagnostics import (
    ai_provider_operator_notice,
    gemini_cooldown_active,
    get_fallback_count_24h,
    get_last_gemini_error,
    get_last_gemini_quota_error,
    get_last_provider_used,
    get_recent_ai_provider_error_buckets,
)


def classify_gemini_error(text: str | None) -> str:
    """Stable buckets for ops dashboards (best-effort string match)."""
    t = (text or "").strip().lower()
    if not t:
        return "none"
    if "provider_forbidden" in t:
        return "provider_forbidden"
    if "403" in t and "quota" not in t and "resource_exhausted" not in t and "resource exhausted" not in t:
        return "provider_forbidden"
    if "429" in t or "quota" in t or "resource_exhausted" in t or "resource exhausted" in t:
        return "quota_rate_limit"
    if "rate" in t and "limit" in t:
        return "rate_limit"
    if "deadline" in t or "timeout" in t or "timed out" in t:
        return "timeout"
    if "json" in t and ("invalid" in t or "parse" in t or "unexpected" in t):
        return "invalid_json"
    if (
        "api key" in t
        or "api_key" in t
        or "invalid api" in t
        or "permission_denied" in t
        or ("missing" in t and "key" in t)
    ):
        return "api_key_invalid"
    if "503" in t or "unavailable" in t or "overload" in t:
        return "provider_unavailable"
    return "provider_error"


def fallback_effectively_active(*, fallback_count_24h: int, last_provider: str | None) -> bool:
    if int(fallback_count_24h or 0) > 0:
        return True
    lp = (last_provider or "").strip().lower()
    if lp in {"fallback", "local", "deterministic"}:
        return True
    if gemini_cooldown_active() or ai_provider_operator_notice():
        return True
    return False


def compute_ai_operational_status(
    *,
    gemini_status: str,
    has_gemini_key: bool,
    provider_name: str,
    last_gemini_error: str | None,
    quota_error: str | None,
    fallback_count_24h: int,
) -> tuple[str, bool, str | None, str]:
    """
    Returns:
      status: ok | degraded | fail
      fallback_active: bool
      suggested_action: optional short string for admins
      error_class: classification bucket
    """
    enable = bool(getattr(settings, "ENABLE_AI_SUGGESTIONS", False))
    merged_err = " ".join(x for x in [last_gemini_error or "", quota_error or ""] if x).strip()
    err_class = classify_gemini_error(merged_err)
    last_pv = get_last_provider_used()
    fb_ok = fallback_effectively_active(fallback_count_24h=fallback_count_24h, last_provider=last_pv)

    gs = (gemini_status or "").strip().lower()
    pn = (provider_name or "").strip().lower()

    sticky_err = bool((last_gemini_error or "").strip()) or bool((quota_error or "").strip())

    # Missing API key: critical only if fallback cannot cover user-facing AI.
    if not has_gemini_key and pn == "gemini" and enable:
        if fb_ok:
            return (
                "degraded",
                True,
                "Gemini API key not configured; deterministic fallback is active.",
                "api_key_missing",
            )
        return ("fail", False, "Configure GEMINI_API_KEY or switch AI provider — no fallback signal.", "api_key_missing")

    if gs == "disabled" and not enable:
        return ("ok", False, None, "none")

    # 403 permission / API disabled / wrong model — not quota; degraded when fallback works.
    if err_class == "provider_forbidden" and sticky_err:
        msg = (
            "Gemini 403 Forbidden / permission issue. "
            "Check Google AI API key, enabled Generative Language API, model access, and billing/free-tier limits."
        )
        if fb_ok:
            return ("degraded", True, msg + " Fallback is protecting users.", err_class)
        return ("fail", False, msg + " No healthy fallback signal detected.", err_class)

    # Free-tier / quota / cooldown — expected noise; never critical if fallback path exists.
    if err_class in {"quota_rate_limit", "rate_limit"} or gemini_cooldown_active():
        msg = "Gemini free-tier/provider errors detected. Fallback is active."
        if fb_ok:
            return ("degraded", True, msg + " Upgrade Google AI billing or wait for quota reset.", err_class)
        return ("fail", False, msg + " Fallback did not activate — verify AI fallback paths.", err_class)

    if sticky_err:
        if fb_ok:
            return (
                "degraded",
                True,
                "Gemini free-tier/provider errors detected. Fallback is active.",
                err_class,
            )
        if err_class == "api_key_invalid":
            return ("fail", False, "Gemini API key appears invalid and no fallback signal.", err_class)
        return ("fail", False, "Gemini provider errors with no fallback signal — investigate immediately.", err_class)

    if gs == "error":
        return ("degraded", fb_ok, "Gemini status error — confirm provider health.", err_class)

    return ("ok", fb_ok, None, err_class)


_GEMINI_ALERT_COOLDOWN_S = 900.0
_gemini_alert_bucket_ts: dict[str, float] = {}


def gemini_alert_bucket_should_emit(dedupe_bucket: str, *, now: float | None = None) -> bool:
    """Cooldown so repeated Gemini noise does not spam Telegram/admin alerts."""
    t = float(now if now is not None else time.time())
    key = hashlib.sha256(dedupe_bucket.encode("utf-8")).hexdigest()[:24]
    prev = float(_gemini_alert_bucket_ts.get(key) or 0.0)
    if t - prev < _GEMINI_ALERT_COOLDOWN_S:
        return False
    _gemini_alert_bucket_ts[key] = t
    return True


def verify_fallback_suggestion_engine() -> dict[str, Any]:
    """Deterministic path used when Gemini fails — must return 3 strings."""
    try:
        from app.services.ab_engine import _fallback_ai_variants

        rows = _fallback_ai_variants("healthcheck")
        ok = isinstance(rows, list) and len(rows) == 3 and all(str(x).strip() for x in rows)
        return {"ok": bool(ok), "suggestions_count": len(rows) if isinstance(rows, list) else 0}
    except Exception as e:
        return {"ok": False, "suggestions_count": 0, "error": str(e)}


def build_system_doctor_ai_extension(
    *,
    gemini_status: str,
    has_gemini_key: bool,
    provider_name: str,
    fallback_count_24h: int,
) -> dict[str, Any]:
    last_err = get_last_gemini_error()
    quota_err = get_last_gemini_quota_error()
    status, fb_act, suggested, err_class = compute_ai_operational_status(
        gemini_status=gemini_status,
        has_gemini_key=has_gemini_key,
        provider_name=provider_name,
        last_gemini_error=last_err,
        quota_error=quota_err,
        fallback_count_24h=int(fallback_count_24h or 0),
    )
    engine_probe = verify_fallback_suggestion_engine()
    agg = get_recent_ai_provider_error_buckets(limit=5)
    recent: list[dict[str, Any]] = list(agg) if agg else []
    if not recent:
        if last_err:
            recent.append(
                {
                    "source": "last_gemini_error",
                    "message": str(last_err)[:800],
                    "classification": err_class,
                    "count": 1,
                    "last_seen_iso": None,
                    "endpoint": "generateContent",
                    "provider": "gemini",
                }
            )
        if quota_err and str(quota_err).strip() != str(last_err or "").strip():
            recent.append(
                {
                    "source": "quota_error",
                    "message": str(quota_err)[:800],
                    "classification": "quota_rate_limit",
                    "count": 1,
                    "last_seen_iso": None,
                    "endpoint": "generateContent",
                    "provider": "gemini",
                }
            )
    recent = recent[:5]

    fb_engine_ok = bool(engine_probe.get("ok"))
    fb_roundtrip_ok = fb_engine_ok and (
        bool(int(fallback_count_24h or 0) > 0)
        or fallback_effectively_active(fallback_count_24h=int(fallback_count_24h or 0), last_provider=get_last_provider_used())
    )

    gem_layer = None
    if err_class == "provider_forbidden":
        gem_layer = "gemini_403_forbidden"
    elif err_class in {"quota_rate_limit", "rate_limit"} or gemini_cooldown_active():
        gem_layer = "gemini_free_tier_or_quota"
    elif err_class == "timeout":
        gem_layer = "timeout"
    elif err_class == "invalid_json":
        gem_layer = "invalid_json"

    return {
        "ai_operational_status": status,
        "ai_fallback_active": fb_act,
        "ai_fallback_engine_verified": fb_roundtrip_ok,
        "ai_user_suggestions_shape_ok": bool(engine_probe.get("ok") and int(engine_probe.get("suggestions_count") or 0) == 3),
        "gemini_error_classification": err_class,
        "gemini_provider_layer": gem_layer,
        "last_provider_errors": recent,
        "system_doctor_suggested_action": suggested
        or (
            "Check Google AI API key, enabled Generative Language API, model access, and billing/free-tier limits. Fallback is protecting users."
            if status == "degraded" and err_class == "provider_forbidden"
            else (
                "Upgrade Google AI billing or wait for quota reset. Fallback is protecting users."
                if status == "degraded"
                else None
            )
        ),
        "gemini_permission_issue": bool(err_class == "provider_forbidden"),
    }
