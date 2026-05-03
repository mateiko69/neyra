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


def _patch_command_center_sources(
    monkeypatch,
    *,
    founder_alerts: list[dict] | None = None,
    autopilot_suggestions: list[dict] | None = None,
    database_status: str = "ok",
    api_errors_24h: int = 0,
    technical_health_score: int = 90,
    open_reports: int = 0,
    secret_text: str = "",
) -> None:
    def _stats(period, admin_user, db):
        return {
            "users": {"new": 3, "active": 11},
            "dating": {"matches": 5, "messages": 21},
            "ai": {"ai_calls": 8},
            "premium": {"premium_users": 2},
            "safety": {"open_reports": open_reports},
        }

    def _system(admin_user, db):
        return {
            "api_status": "ok",
            "database_status": database_status,
            "redis_status": "ok",
            "api_errors_24h": api_errors_24h,
            "ai_fallback_count_24h": 0,
        }

    def _premium(admin_user, db):
        return {"premium_users": 2}

    def _cto(period, admin_user, db):
        return {
            "technical_health_score": technical_health_score,
            "top_engineering_priority": {
                "title": "Stabilize core systems",
                "reason": "Backend risk",
                "recommended_action": "Fix top errors",
            },
        }

    def _autopilot(admin_user, db):
        return {"suggestions": autopilot_suggestions or []}

    def _founder(admin_user, db):
        return {
            "date": "2026-04-26",
            "north_star": {"metric": "Daily active conversations", "value": 11, "trend": "up"},
            "today_plan": [
                {
                    "priority": 1,
                    "title": "Improve AI replies",
                    "reason": f"High edit rate {secret_text}".strip(),
                    "expected_impact": "high",
                    "action": f"Tune prompts {secret_text}".strip(),
                }
            ],
            "alerts": founder_alerts or [],
            "wins": [],
            "focus": "Improve conversation quality",
        }

    monkeypatch.setattr(admin_mod, "admin_stats_overview", _stats)
    monkeypatch.setattr(admin_mod, "system_doctor", _system)
    monkeypatch.setattr(admin_mod, "admin_premium_overview", _premium)
    monkeypatch.setattr(admin_mod, "admin_cto_roadmap", _cto)
    monkeypatch.setattr(admin_mod, "admin_autopilot_suggestions", _autopilot)
    monkeypatch.setattr(admin_mod, "admin_founder_daily", _founder)


def test_command_center_home_endpoint_shape(monkeypatch):
    _patch_command_center_sources(monkeypatch)
    res = _client(db=object()).get("/api/v1/admin/command-center/home")
    assert res.status_code == 200
    payload = res.json()
    assert payload["status"] in {"healthy", "warning", "critical"}
    assert isinstance(payload["headline"], str)
    assert set(payload["today"].keys()) == {
        "new_users",
        "active_users",
        "matches",
        "messages",
        "ai_calls",
        "premium_users",
        "open_reports",
    }
    assert set(payload["top_recommendation"].keys()) == {"title", "reason", "action"}
    assert isinstance(payload["critical_alerts"], list)
    assert any(action["id"] == "system_doctor" for action in payload["quick_actions"])


def test_command_center_status_calculation(monkeypatch):
    _patch_command_center_sources(monkeypatch)
    assert _client(db=object()).get("/api/v1/admin/command-center/home").json()["status"] == "healthy"

    _patch_command_center_sources(
        monkeypatch,
        autopilot_suggestions=[
            {
                "id": "clear_cache",
                "title": "Clear Redis cache",
                "reason": "Cache hit ratio is low",
                "impact": "medium",
                "risk": "low",
                "action_endpoint": "/api/v1/admin/system/clear-cache",
            }
        ],
    )
    assert _client(db=object()).get("/api/v1/admin/command-center/home").json()["status"] == "warning"

    _patch_command_center_sources(
        monkeypatch,
        founder_alerts=[{"level": "critical", "message": "Database health is not OK", "suggested_fix": "Review migrations"}],
    )
    payload = _client(db=object()).get("/api/v1/admin/command-center/home").json()
    assert payload["status"] == "critical"
    assert payload["critical_alerts"][0]["level"] == "critical"


def test_command_center_no_private_content_or_secrets(monkeypatch):
    _patch_command_center_sources(
        monkeypatch,
        secret_text="api_key=BAD password=NOPE raw_messages private chats email=owner@example.com",
        founder_alerts=[
            {
                "level": "critical",
                "message": "api_key=BAD private chats",
                "suggested_fix": "password=NOPE email=owner@example.com",
            }
        ],
    )
    res = _client(db=object()).get("/api/v1/admin/command-center/home")
    assert res.status_code == 200
    raw = res.text.lower()
    assert "bad" not in raw
    assert "nope" not in raw
    assert "api_key" not in raw
    assert "password" not in raw
    assert "raw_messages" not in raw
    assert "private chats" not in raw
    assert "owner@example.com" not in raw
