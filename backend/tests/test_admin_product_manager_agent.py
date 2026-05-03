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


def test_product_manager_daily_brief_shape_and_score_range():
    c = _client()
    r = c.get("/api/v1/admin/product-manager/daily-brief", params={"period": "7d"})
    assert r.status_code == 200
    j = r.json()
    assert j["period"] in {"today", "7d", "30d"}
    assert "health_score" in j
    assert 0 <= int(j["health_score"]) <= 100
    assert "top_priority" in j
    assert "priorities" in j
    assert "wins" in j and "risks" in j and "next_actions" in j
    tp = j["top_priority"]
    for k in ["title", "reason", "impact", "effort", "recommended_action"]:
        assert k in tp


def test_product_manager_priorities_no_private_data():
    c = _client()
    j = c.get("/api/v1/admin/product-manager/daily-brief", params={"period": "today"}).json()
    pr = j.get("priorities") or []
    assert isinstance(pr, list)
    for row in pr[:10]:
        # Must not include message content or user identifiers.
        s = str(row).lower()
        assert "content" not in s
        assert "messages" not in s
        assert "email" not in s
        assert "phone" not in s

