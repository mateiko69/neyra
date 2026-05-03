from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.deps import get_admin_user, get_admin_actor, get_db
from app.api.v1.endpoints import admin as admin_mod


class DummyAdmin:
    id = 999
    email = "admin@example.com"


def _client(db=None) -> TestClient:
    app = FastAPI()
    app.include_router(admin_mod.router, prefix="/api/v1/admin")
    app.dependency_overrides[get_admin_user] = lambda: DummyAdmin()
    app.dependency_overrides[get_admin_actor] = lambda: DummyAdmin()
    if db is not None:
        app.dependency_overrides[get_db] = lambda: db
    return TestClient(app)


def _patch_alert_sources(
    monkeypatch,
    *,
    database_status: str = "ok",
    redis_status: str = "ok",
    api_errors_24h: int = 0,
    fallback_24h: int = 0,
    last_gemini_error: str | None = None,
    open_reports: int = 0,
    new_reports: int = 0,
    banned_users: int = 0,
    dead_chats: int = 0,
    weak_matches: int = 0,
    expiring_trials_24h: int = 0,
    paywall_views: int = 0,
    premium_conversion_rate: float = 0.0,
    localization_issues: int = 0,
) -> None:
    def _system(admin_user, db):
        gem_cls = "provider_error"
        if last_gemini_error and ("429" in last_gemini_error or "quota" in last_gemini_error.lower()):
            gem_cls = "quota_rate_limit"
        ai_op = (
            "fail"
            if last_gemini_error and fallback_24h <= 0 and gem_cls not in {"quota_rate_limit", "rate_limit"}
            else ("degraded" if last_gemini_error else "ok")
        )
        return {
            "api_status": "ok",
            "database_status": database_status,
            "redis_status": redis_status,
            "gemini_status": "error" if last_gemini_error else "ok",
            "last_gemini_error": last_gemini_error,
            "api_errors_24h": api_errors_24h,
            "ai_fallback_count_24h": fallback_24h,
            "ai_operational_status": ai_op,
            "ai_fallback_active": fallback_24h > 0,
            "gemini_error_classification": gem_cls,
        }

    def _stats(period, admin_user, db):
        return {
            "users": {"new": 0, "active": 0},
            "dating": {"matches": 0, "messages": 0},
            "ai": {"ai_calls": 0},
            "premium": {"premium_users": 0},
            "safety": {"open_reports": open_reports, "new_reports": new_reports, "banned_users": banned_users},
        }

    def _match_quality(admin_user, db):
        return {"dead_chats_count": dead_chats, "weak_matches_count": weak_matches}

    def _premium(admin_user, db):
        return {"expiring_trials_24h": expiring_trials_24h}

    def _growth(period, admin_user, db):
        return {"monetization": {"paywall_views": paywall_views, "premium_conversion_rate": premium_conversion_rate}}

    def _l10n(admin_user):
        return {"summary": {"hardcoded_strings": localization_issues}}

    monkeypatch.setattr(admin_mod, "system_doctor", _system)
    monkeypatch.setattr(admin_mod, "admin_stats_overview", _stats)
    monkeypatch.setattr(admin_mod, "admin_match_quality_overview", _match_quality)
    monkeypatch.setattr(admin_mod, "admin_premium_overview", _premium)
    monkeypatch.setattr(admin_mod, "admin_growth_overview", _growth)
    monkeypatch.setattr(admin_mod, "localization_quality", _l10n)


def test_alerts_poll_endpoint_shape(monkeypatch):
    _patch_alert_sources(
        monkeypatch,
        database_status="error",
        api_errors_24h=30,
        last_gemini_error="provider failed",
        open_reports=12,
        dead_chats=40,
        expiring_trials_24h=3,
        paywall_views=80,
        premium_conversion_rate=0.01,
        localization_issues=30,
    )
    res = _client(db=object()).get("/api/v1/admin/alerts/poll")
    assert res.status_code == 200
    payload = res.json()
    assert set(payload.keys()) == {"alerts"}
    assert isinstance(payload["alerts"], list)
    assert payload["alerts"]
    for alert in payload["alerts"]:
        assert set(alert.keys()) == {"id", "level", "title", "message", "source", "created_at", "dedupe_key", "action"}
        assert alert["level"] in {"critical", "warning", "info"}
        assert alert["source"] in {"system", "ai", "safety", "premium", "growth", "matches"}
        assert set(alert["action"].keys()) == {"label", "callback"}
        assert alert["action"]["callback"].startswith("m:")


def test_alerts_poll_no_secrets_or_private_content(monkeypatch):
    _patch_alert_sources(
        monkeypatch,
        database_status="api_key=BAD",
        last_gemini_error="password=NOPE private chats owner@example.com",
        api_errors_24h=40,
    )
    res = _client(db=object()).get("/api/v1/admin/alerts/poll")
    assert res.status_code == 200
    raw = res.text.lower()
    assert "bad" not in raw
    assert "nope" not in raw
    assert "api_key" not in raw
    assert "password" not in raw
    assert "private chats" not in raw
    assert "owner@example.com" not in raw


def test_alert_dedupe_helper_keeps_one_per_key():
    alerts: list[dict] = []
    seen: set[str] = set()
    base = {
        "level": "warning",
        "title": "API errors detected",
        "message": "Errors rose above threshold.",
        "source": "system",
        "dedupe_key": "system:api_errors_detected",
        "action_label": "Open System Doctor",
        "action_callback": "m:system",
        "created_at": "2026-04-26T00:00:00+00:00",
    }
    admin_mod._append_admin_alert(alerts, seen, alert_id="first", **base)
    admin_mod._append_admin_alert(alerts, seen, alert_id="second", **base)
    assert len(alerts) == 1
    assert alerts[0]["id"] == "first"
