from __future__ import annotations

import pytest

from app.core.config import settings
from app.services.ai.health_snapshot import (
    classify_gemini_error,
    compute_ai_operational_status,
    gemini_alert_bucket_should_emit,
    verify_fallback_suggestion_engine,
)


def test_classify_gemini_error_buckets():
    assert classify_gemini_error("429 resource exhausted") == "quota_rate_limit"
    assert classify_gemini_error("rate limit exceeded") == "rate_limit"
    assert classify_gemini_error("deadline exceeded timeout") == "timeout"
    assert classify_gemini_error("invalid json parse error") == "invalid_json"
    assert classify_gemini_error("API key invalid") == "api_key_invalid"
    assert classify_gemini_error("503 unavailable") == "provider_unavailable"


def test_gemini_429_with_fallback_is_degraded_not_fail(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "ENABLE_AI_SUGGESTIONS", True)
    st, fb, _, cls = compute_ai_operational_status(
        gemini_status="ok",
        has_gemini_key=True,
        provider_name="gemini",
        last_gemini_error="429: exhausted",
        quota_error=None,
        fallback_count_24h=5,
        last_provider_used="fallback",
    )
    assert st == "degraded"
    assert fb is True
    assert cls == "quota_rate_limit"


def test_gemini_failure_without_fallback_is_fail(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "ENABLE_AI_SUGGESTIONS", True)
    st, fb, _, _ = compute_ai_operational_status(
        gemini_status="ok",
        has_gemini_key=True,
        provider_name="gemini",
        last_gemini_error="503: unavailable",
        quota_error=None,
        fallback_count_24h=0,
        last_provider_used="gemini",
    )
    assert st == "fail"
    assert fb is False


def test_missing_gemini_key_with_fallback_not_critical(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "ENABLE_AI_SUGGESTIONS", True)
    st, fb, _, cls = compute_ai_operational_status(
        gemini_status="disabled",
        has_gemini_key=False,
        provider_name="gemini",
        last_gemini_error=None,
        quota_error=None,
        fallback_count_24h=2,
        last_provider_used="fallback",
    )
    assert st == "degraded"
    assert fb is True
    assert cls == "api_key_missing"


def test_verify_fallback_engine_returns_three():
    out = verify_fallback_suggestion_engine()
    assert out.get("ok") is True
    assert int(out.get("suggestions_count") or 0) == 3


def test_gemini_alert_bucket_cooldown(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "app.services.ai.health_snapshot._gemini_alert_bucket_ts",
        {},
    )
    assert gemini_alert_bucket_should_emit("k1", now=1000.0) is True
    assert gemini_alert_bucket_should_emit("k1", now=1005.0) is False
    assert gemini_alert_bucket_should_emit("k1", now=2000.0) is True
