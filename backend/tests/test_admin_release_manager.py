from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.deps import get_admin_user, get_admin_actor, get_db
from app.api.v1.endpoints import admin as admin_mod
from app.core.config import settings


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


def _patch_release_sources(
    monkeypatch,
    *,
    database_status: str = "ok",
    api_status: str = "ok",
    redis_status: str = "ok",
    api_errors_24h: int = 0,
    critical_alerts: int = 0,
    backup_recent: bool = True,
    open_reports: int = 0,
    localization_issues: int = 0,
) -> None:
    def _system(admin_user, db):
        return {
            "api_status": api_status,
            "database_status": database_status,
            "redis_status": redis_status,
            "alembic_revision": "abc123",
            "gemini_status": "ok",
            "last_gemini_error": None,
            "api_errors_24h": api_errors_24h,
            "ai_fallback_count_24h": 0,
        }

    def _stats(period, admin_user, db):
        return {"safety": {"open_reports": open_reports}}

    def _alerts(admin_user, db):
        return {
            "alerts": [
                {
                    "id": f"critical_{i}",
                    "level": "critical",
                    "title": "Critical alert",
                    "message": "Critical aggregate issue",
                    "source": "system",
                    "created_at": "2026-04-26T00:00:00+00:00",
                    "dedupe_key": f"critical:{i}",
                    "action": {"label": "Open System Doctor", "callback": "m:system"},
                }
                for i in range(critical_alerts)
            ]
        }

    def _l10n(admin_user):
        return {"summary": {"hardcoded_strings": localization_issues}}

    monkeypatch.setattr(admin_mod, "system_doctor", _system)
    monkeypatch.setattr(admin_mod, "admin_stats_overview", _stats)
    monkeypatch.setattr(admin_mod, "admin_alerts_poll", _alerts)
    monkeypatch.setattr(admin_mod, "localization_quality", _l10n)
    monkeypatch.setattr(admin_mod, "_release_backup_recent", lambda hours=24: (backup_recent, "Fresh backup"))
    monkeypatch.setattr(admin_mod, "_release_tests_check", lambda: admin_mod._release_check("tests", "Backend tests", "pass", "165 tests passed", True))
    monkeypatch.setattr(settings, "ENV", "development")
    monkeypatch.setattr(settings, "PAYMENTS_PROVIDER", "mock")

    def _menu_qa(admin_actor):
        return {
            "status": "pass",
            "summary": {
                "missing_handlers": 0,
                "render_errors": 0,
                "unsafe_actions": 0,
                "menus_checked": 1,
                "buttons_checked": 1,
                "callbacks_checked": 1,
            },
        }

    def _cov():
        return {
            "locales": [
                {"code": "en", "coverage": 100, "coverage_present_pct": 100, "missing": 0, "raw_keys": 0},
                {"code": "uk", "coverage": 72, "coverage_present_pct": 99, "missing": 0, "raw_keys": 0},
            ],
            "summary": {
                "missing_keys_total": 0,
                "raw_value_leaks_total": 0,
                "en_fallback_keys_total": 120,
            },
        }

    monkeypatch.setattr(admin_mod, "admin_telegram_menu_qa_scan", _menu_qa)
    monkeypatch.setattr(admin_mod, "compute_localization_coverage", _cov)


def test_release_readiness_shape(monkeypatch):
    _patch_release_sources(monkeypatch)
    res = _client(db=object()).get("/api/v1/admin/release/readiness")
    assert res.status_code == 200
    payload = res.json()
    assert set(payload.keys()) == {"ready", "score", "environment", "checks", "blockers", "warnings", "recommended_actions"}
    assert isinstance(payload["ready"], bool)
    assert isinstance(payload["checks"], list)
    assert payload["checks"]
    for row in payload["checks"]:
        assert set(row.keys()) == {"id", "title", "status", "details", "blocking"}
        assert row["status"] in {"pass", "warning", "fail"}


def test_release_readiness_score_range(monkeypatch):
    _patch_release_sources(monkeypatch, open_reports=10, localization_issues=30)
    payload = _client(db=object()).get("/api/v1/admin/release/readiness").json()
    assert 0 <= payload["score"] <= 100


def test_release_readiness_score_high_when_healthy_dev_even_without_backup(monkeypatch):
    _patch_release_sources(monkeypatch, backup_recent=False)
    payload = _client(db=object()).get("/api/v1/admin/release/readiness").json()
    assert payload["score"] > 55
    assert any(row["id"] == "backup_recent" and row["status"] == "warning" for row in payload["checks"])


def test_release_readiness_score_at_least_50_when_core_passes_despite_extra_warnings(monkeypatch):
    _patch_release_sources(monkeypatch, backup_recent=False, open_reports=10, localization_issues=25)

    def _warn_tests():
        return admin_mod._release_check(
            "tests",
            "Backend tests",
            "warning",
            "3 cached failing tests detected locally (dev: non-blocking; clear .pytest_cache or fix tests).",
            False,
        )

    monkeypatch.setattr(admin_mod, "_release_tests_check", _warn_tests)
    payload = _client(db=object()).get("/api/v1/admin/release/readiness").json()
    assert payload["score"] >= 50


def test_release_readiness_blockers_if_critical_system_unhealthy(monkeypatch):
    _patch_release_sources(monkeypatch, database_status="error")
    payload = _client(db=object()).get("/api/v1/admin/release/readiness").json()
    assert payload["ready"] is False
    assert "DB healthy" in payload["blockers"]
    assert any(row["id"] == "db_health" and row["status"] == "fail" for row in payload["checks"])


def test_release_mark_requires_confirm():
    res = _client().post("/api/v1/admin/release/mark", json={"version": "0.1.0", "notes": "test"})
    assert res.status_code == 400
    assert res.json().get("detail", {}).get("error") == "confirm_required"


def test_release_mark_logs_marker():
    res = _client().post("/api/v1/admin/release/mark", json={"version": "0.1.0", "notes": "Initial beta", "confirm": True})
    assert res.status_code == 200
    payload = res.json()
    assert payload["ok"] is True
    assert payload["version"] == "0.1.0"
    audit = _client().get("/api/v1/admin/audit-log", params={"action_type": "release_mark"})
    assert audit.status_code == 200
    assert any(row["metadata"].get("version") == "0.1.0" for row in audit.json()["items"])
