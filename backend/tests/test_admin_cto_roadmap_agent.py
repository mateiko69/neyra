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
    app.dependency_overrides[get_admin_user] = lambda: DummyAdmin()
    app.dependency_overrides[get_admin_actor] = lambda: DummyAdmin()
    app.dependency_overrides[get_db] = _get_db_override
    return TestClient(app)


def test_cto_roadmap_shape_and_score_range():
    c = _client()
    r = c.get("/api/v1/admin/cto/roadmap", params={"period": "7d"})
    assert r.status_code == 200
    j = r.json()
    assert j["period"] in {"today", "7d", "30d"}
    assert "technical_health_score" in j
    assert 0 <= int(j["technical_health_score"]) <= 100
    assert "top_engineering_priority" in j
    assert "priorities" in j
    assert "technical_debt" in j and "risks" in j and "next_actions" in j
    tep = j["top_engineering_priority"]
    for k in ["title", "reason", "impact", "risk", "recommended_action"]:
        assert k in tep


def test_cto_priorities_no_secrets_or_private_data():
    c = _client()
    j = c.get("/api/v1/admin/cto/roadmap", params={"period": "today"}).json()
    pr = j.get("priorities") or []
    assert isinstance(pr, list)
    for row in pr[:10]:
        s = str(row).lower()
        # No secrets / keys / message content / raw user identifiers.
        assert "api_key" not in s
        assert "gemini_api_key" not in s
        assert "authorization" not in s
        assert "content" not in s
        assert "messages" not in s
        assert "email" not in s

