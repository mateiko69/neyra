from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.deps import get_admin_user, get_admin_actor, get_db
from app.api.v1.endpoints import admin as admin_mod
from app.core.config import settings
from app.db.base import Base


class DummyAdmin:
    id = 999
    email = "admin@example.com"


def _client() -> TestClient:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    import app.models  # noqa: F401
    Base.metadata.create_all(engine)

    def _get_db_override():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app = FastAPI()
    app.include_router(admin_mod.router, prefix="/api/v1/admin")
    app.dependency_overrides[get_admin_user] = lambda: DummyAdmin()
    app.dependency_overrides[get_admin_actor] = lambda: DummyAdmin()
    app.dependency_overrides[get_db] = _get_db_override
    return TestClient(app)


def test_autopilot_suggestions_endpoint_shape_and_no_secrets():
    c = _client()
    res = c.get("/api/v1/admin/autopilot/suggestions")
    assert res.status_code == 200
    payload = res.json()
    assert set(payload.keys()) == {"suggestions"}
    assert isinstance(payload["suggestions"], list)
    for item in payload["suggestions"]:
        assert set(item.keys()) == {"id", "title", "reason", "impact", "risk", "action_endpoint"}
        assert item["id"] in admin_mod.AUTOPILOT_ACTIONS
        assert item["action_endpoint"].startswith("/api/v1/admin/")
    raw = res.text.lower()
    assert "api_key" not in raw
    assert "secret_key" not in raw
    assert "password" not in raw
    assert "private chat" not in raw


def test_autopilot_execute_requires_confirm():
    c = _client()
    res = c.post("/api/v1/admin/autopilot/execute", json={"action_id": "clear_cache"})
    assert res.status_code == 400
    assert res.json().get("detail", {}).get("error") == "confirm_required"


def test_autopilot_execute_maps_to_existing_function_and_redacts(monkeypatch):
    c = _client()
    called = {}

    def _fake_clear_cache(admin_user, db, payload):
        called["admin_id"] = int(admin_user.id)
        called["payload"] = payload
        return {"ok": True, "cleared": {"redis": False}, "api_key": "super-secret-value"}

    monkeypatch.setattr(admin_mod, "system_clear_cache", _fake_clear_cache)
    res = c.post("/api/v1/admin/autopilot/execute", json={"action_id": "clear_cache", "confirm": True})
    assert res.status_code == 200
    payload = res.json()
    assert called == {"admin_id": 999, "payload": {"confirm": True}}
    assert payload["status"] == "executed"
    assert payload["action_endpoint"] == "/api/v1/admin/system/clear-cache"
    assert payload["result"]["api_key"] == "[redacted]"
    assert "super-secret-value" not in res.text


def test_autopilot_blocks_dangerous_actions_in_production(monkeypatch):
    monkeypatch.setattr(settings, "ENV", "production")
    c = _client()
    res = c.post("/api/v1/admin/autopilot/execute", json={"action_id": "grant-all-dev", "confirm": True})
    assert res.status_code == 403
    assert res.json().get("detail", {}).get("error") == "blocked_in_production"
