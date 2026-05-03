from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.deps import get_db
from app.api.v1.endpoints.admin import router as admin_router
from app.core.config import settings
from app.db.base import Base


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
    app.include_router(admin_router, prefix="/api/v1/admin")
    app.dependency_overrides[get_db] = _get_db_override
    return TestClient(app)


def test_admin_endpoint_accepts_valid_service_token(monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_BOT_SERVICE_TOKEN", "test-service-token")
    res = _client().get("/api/v1/admin/system-doctor", headers={"X-Admin-Service-Token": "test-service-token"})
    assert res.status_code == 200


def test_admin_endpoint_rejects_missing_service_token(monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_BOT_SERVICE_TOKEN", "test-service-token")
    res = _client().get("/api/v1/admin/system-doctor")
    assert res.status_code == 401


def test_admin_endpoint_rejects_invalid_service_token(monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_BOT_SERVICE_TOKEN", "test-service-token")
    res = _client().get("/api/v1/admin/system-doctor", headers={"X-Admin-Service-Token": "wrong"})
    assert res.status_code == 401

