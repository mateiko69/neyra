from __future__ import annotations

import re

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


def _patch_founder_sources(monkeypatch, *, priorities_count: int = 3, secret_text: str = "") -> None:
    def _stats(period, admin_user, db):
        active = 12 if period == "today" else 70
        return {"dating": {"active_chats": active}}

    def _pm(period, admin_user, db):
        priorities = [
            {
                "title": f"Improve AI replies {i}",
                "reason": f"High edit rate {secret_text}".strip(),
                "impact": "high",
                "effort": "low",
                "recommended_action": "Tune prompts and measure reply outcomes",
            }
            for i in range(priorities_count)
        ]
        return {
            "top_priority": priorities[0] if priorities else {},
            "priorities": priorities,
            "wins": [{"title": "Premium conversion is healthy", "metric": "conversion_rate=0.10"}],
        }

    def _growth(period, admin_user, db):
        return {
            "recommendations": [
                {"priority": "high", "title": "Increase profile completion", "reason": "Activation is low", "action": "Tighten onboarding prompts"}
            ]
        }

    def _conv(period, admin_user, db):
        return {"issues": [{"severity": "high", "message": "High edit rate detected"}]}

    def _mq(admin_user, db):
        return {"dead_chats_count": 4, "weak_matches_count": 2}

    def _premium(admin_user, db):
        return {"expiring_trials_24h": 1}

    def _system(admin_user, db):
        return {"database_status": "ok", "api_errors_24h": 0, "ai_fallback_count_24h": 0, "gemini_status": "ok"}

    def _cto(period, admin_user, db):
        return {
            "top_engineering_priority": {
                "title": "Reduce API errors",
                "reason": "Stability risk",
                "impact": "high",
                "risk": "high",
                "recommended_action": "Fix top exceptions",
            },
            "priorities": [],
        }

    def _autopilot(admin_user, db):
        return {
            "suggestions": [
                {
                    "id": "localization_scan",
                    "title": "Run localization scan",
                    "reason": "Mixed language strings detected",
                    "impact": "medium",
                    "risk": "low",
                    "action_endpoint": "/api/v1/admin/localization/scan",
                }
            ]
        }

    monkeypatch.setattr(admin_mod, "admin_stats_overview", _stats)
    monkeypatch.setattr(admin_mod, "admin_product_manager_daily_brief", _pm)
    monkeypatch.setattr(admin_mod, "admin_growth_overview", _growth)
    monkeypatch.setattr(admin_mod, "admin_conversation_quality_overview", _conv)
    monkeypatch.setattr(admin_mod, "admin_match_quality_overview", _mq)
    monkeypatch.setattr(admin_mod, "admin_premium_overview", _premium)
    monkeypatch.setattr(admin_mod, "system_doctor", _system)
    monkeypatch.setattr(admin_mod, "admin_cto_roadmap", _cto)
    monkeypatch.setattr(admin_mod, "admin_autopilot_suggestions", _autopilot)


def test_founder_daily_endpoint_shape(monkeypatch):
    _patch_founder_sources(monkeypatch)
    res = _client(db=object()).get("/api/v1/admin/founder/daily")
    assert res.status_code == 200
    payload = res.json()
    assert re.match(r"^\d{4}-\d{2}-\d{2}$", payload["date"])
    assert set(payload["north_star"].keys()) == {"metric", "value", "trend"}
    assert payload["north_star"]["metric"] == "Daily active conversations"
    assert payload["north_star"]["trend"] in {"up", "down", "flat"}
    assert isinstance(payload["today_plan"], list)
    assert isinstance(payload["alerts"], list)
    assert isinstance(payload["wins"], list)
    assert isinstance(payload["focus"], str)
    for row in payload["today_plan"]:
        assert set(row.keys()) == {"priority", "title", "reason", "expected_impact", "action"}


def test_founder_daily_max_five_priorities(monkeypatch):
    _patch_founder_sources(monkeypatch, priorities_count=12)
    payload = _client(db=object()).get("/api/v1/admin/founder/daily").json()
    assert len(payload["today_plan"]) <= 5
    assert [row["priority"] for row in payload["today_plan"]] == list(range(1, len(payload["today_plan"]) + 1))


def test_founder_daily_no_private_content_or_secrets(monkeypatch):
    _patch_founder_sources(monkeypatch, priorities_count=2, secret_text="api_key=BAD password=NOPE raw_messages")
    res = _client(db=object()).get("/api/v1/admin/founder/daily")
    assert res.status_code == 200
    raw = res.text.lower()
    assert "bad" not in raw
    assert "nope" not in raw
    assert "api_key" not in raw
    assert "password" not in raw
    assert "raw_messages" not in raw
    assert "email" not in raw
    assert "private" not in raw
