"""
Admin Telegram proxy security: service token gates, unknown viewer_user_id, analytics allowlist.
Does not touch .env — uses monkeypatch on settings.ADMIN_BOT_SERVICE_TOKEN.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.deps import get_db
from app.api.v1.endpoints import admin_telegram
from app.api.v1.endpoints.admin import router as admin_router
from app.core.config import settings
from app.db.base import Base
from app.models.user import User


def _make_client():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    import app.models  # noqa: F401
    Base.metadata.create_all(engine)

    def _db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app = FastAPI()
    app.include_router(admin_router, prefix="/api/v1/admin")
    app.include_router(admin_telegram.router, prefix="/api/v1/admin")
    app.dependency_overrides[get_db] = _db
    return TestClient(app), TestingSessionLocal


def test_telegram_diagnostics_requires_service_token(monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_BOT_SERVICE_TOKEN", "valid-service-token")
    client, _ = _make_client()
    assert client.get("/api/v1/admin/telegram/diagnostics").status_code == 401


def test_telegram_diagnostics_rejects_wrong_token(monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_BOT_SERVICE_TOKEN", "valid-service-token")
    client, _ = _make_client()
    r = client.get("/api/v1/admin/telegram/diagnostics", headers={"X-Admin-Service-Token": "bad"})
    assert r.status_code == 401


def test_telegram_diagnostics_ok_with_valid_token(monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_BOT_SERVICE_TOKEN", "valid-service-token")
    client, _ = _make_client()
    r = client.get("/api/v1/admin/telegram/diagnostics", headers={"X-Admin-Service-Token": "valid-service-token"})
    assert r.status_code == 200
    j = r.json()
    assert j.get("api_status") == "ok"
    assert j.get("database_status") == "ok"
    assert "gemini_status" in j
    assert isinstance(j.get("telegram_diagnostic_lines"), list)
    assert isinstance(j.get("telegram_last_errors"), list)
    assert len(j.get("telegram_last_errors") or []) <= 5


def test_analytics_track_requires_token(monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_BOT_SERVICE_TOKEN", "valid-service-token")
    client, _ = _make_client()
    assert (
        client.post("/api/v1/admin/telegram/analytics/track", json={"name": "ai_used", "user_id": 1}).status_code == 401
    )


def test_analytics_track_unknown_event_rejected(monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_BOT_SERVICE_TOKEN", "valid-service-token")
    client, _ = _make_client()
    r = client.post(
        "/api/v1/admin/telegram/analytics/track",
        headers={"X-Admin-Service-Token": "valid-service-token"},
        json={"name": "evil_event", "user_id": 1},
    )
    assert r.status_code == 400


def test_analytics_track_whitelisted_ok(monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_BOT_SERVICE_TOKEN", "valid-service-token")
    client, Session = _make_client()
    db = Session()
    db.add(User(id=10, email="track10@example.com", hashed_password="x"))
    db.commit()
    db.close()

    for name in ("ai_used", "ai_suggestion_used", "ai_limit_hit", "order_created", "shipment_created"):
        r = client.post(
            "/api/v1/admin/telegram/analytics/track",
            headers={"X-Admin-Service-Token": "valid-service-token"},
            json={"name": name, "user_id": 10, "payload": {"probe": True}},
        )
        assert r.status_code == 200, name
        assert r.json().get("ok") is True


def test_chat_copilot_proxy_unknown_viewer_returns_404(monkeypatch):
    """Existing users only — arbitrary viewer_user_id cannot impersonate a missing account."""
    monkeypatch.setattr(settings, "ADMIN_BOT_SERVICE_TOKEN", "valid-service-token")
    client, _ = _make_client()
    r = client.post(
        "/api/v1/admin/telegram/ai/chat-copilot",
        headers={"X-Admin-Service-Token": "valid-service-token"},
        json={"viewer_user_id": 999999, "partner_user_id": 888888},
    )
    assert r.status_code == 404


def test_improve_reply_unknown_viewer_returns_404(monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_BOT_SERVICE_TOKEN", "valid-service-token")
    client, _ = _make_client()
    r = client.post(
        "/api/v1/admin/telegram/ai/improve-reply",
        headers={"X-Admin-Service-Token": "valid-service-token"},
        json={"viewer_user_id": 424242, "draft": "hello"},
    )
    assert r.status_code == 404
