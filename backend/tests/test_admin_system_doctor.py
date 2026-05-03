from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.deps import get_admin_user, get_admin_actor, get_db
from app.api.v1.endpoints.admin import router as admin_router
from app.db.base import Base


class DummyAdmin:
    id = 999
    email = "admin@example.com"


def _build_client() -> TestClient:
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
    app.dependency_overrides[get_admin_user] = lambda: DummyAdmin()
    app.dependency_overrides[get_admin_actor] = lambda: DummyAdmin()
    app.dependency_overrides[get_db] = _get_db_override
    return TestClient(app)


def test_system_doctor_returns_expected_fields():
    client = _build_client()
    res = client.get("/api/v1/admin/system-doctor")
    assert res.status_code == 200
    j = res.json()
    for k in [
        "api_status",
        "database_status",
        "redis_status",
        "alembic_revision",
        "users_count",
        "profiles_count",
        "matches_count",
        "messages_count",
        "gemini_status",
        "gemini_model",
        "last_gemini_error",
        "ai_provider_notice",
        "ai_fallback_count_24h",
        "api_errors_24h",
        "last_10_errors",
        "uptime_seconds",
        "environment",
        "ai_operational_status",
        "ai_fallback_active",
        "last_provider_errors",
    ]:
        assert k in j


def test_dangerous_actions_require_confirm():
    client = _build_client()
    for path in ["/api/v1/admin/system/backup-db", "/api/v1/admin/system/clear-cache", "/api/v1/admin/system/run-migrations"]:
        res = client.post(path, json={})
        assert res.status_code == 400
        assert res.json().get("detail", {}).get("error") == "confirm_required"

