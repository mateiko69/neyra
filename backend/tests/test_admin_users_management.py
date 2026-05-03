from __future__ import annotations

from datetime import UTC, datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.deps import get_admin_user, get_admin_actor, get_db
from app.api.v1.endpoints.admin import router as admin_router
from app.db.base import Base
from app.models.profile import Profile
from app.models.user import User
from app.models.user_ai_memory import UserAiMemory


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
    app.state.TestingSessionLocal = TestingSessionLocal  # type: ignore[attr-defined]
    return TestClient(app)


def test_search_users_by_email_and_name():
    c = _client()
    db = c.app.state.TestingSessionLocal()  # type: ignore[attr-defined]
    try:
        u = User(email="alice@example.com", hashed_password=None, created_at=datetime.now(UTC))
        db.add(u)
        db.commit()
        db.refresh(u)
        db.add(Profile(user_id=u.id, display_name="Alice", city="Kyiv", bio=""))
        db.commit()
        uid = int(u.id)
    finally:
        db.close()
    r = c.get("/api/v1/admin/users/search", params={"q": "alice@"})
    assert r.status_code == 200
    items = r.json()
    assert any(int(x["id"]) == uid for x in items)

    r2 = c.get("/api/v1/admin/users/search", params={"q": "Alice"})
    assert r2.status_code == 200
    assert any(int(x["id"]) == uid for x in r2.json())


def test_user_details_and_actions():
    c = _client()
    db = c.app.state.TestingSessionLocal()  # type: ignore[attr-defined]
    try:
        u = User(email="bob@example.com", hashed_password=None, created_at=datetime.now(UTC))
        db.add(u)
        db.commit()
        db.refresh(u)
        db.add(Profile(user_id=u.id, display_name="Bob", city="Kyiv", bio=""))
        db.commit()
        uid = int(u.id)
        db.add(UserAiMemory(user_id=uid, memory_type="test", key="k", value_json={"v": 1}))
        db.commit()
    finally:
        db.close()

    d = c.get(f"/api/v1/admin/users/{uid}")
    assert d.status_code == 200
    j = d.json()
    assert j["user"]["id"] == uid

    # grant premium requires confirm
    bad = c.post(f"/api/v1/admin/users/{uid}/grant-premium", json={"days": 7})
    assert bad.status_code == 400

    ok = c.post(f"/api/v1/admin/users/{uid}/grant-premium", json={"days": 7, "confirm": True})
    assert ok.status_code == 200

    # revoke premium
    ok2 = c.post(f"/api/v1/admin/users/{uid}/revoke-premium", json={"confirm": True})
    assert ok2.status_code == 200

    # reset memory
    ok3 = c.post(f"/api/v1/admin/users/{uid}/reset-ai-memory", json={"confirm": True})
    assert ok3.status_code == 200

    # ban/unban
    ban_bad = c.post(f"/api/v1/admin/users/{uid}/ban", json={"confirm": True})
    assert ban_bad.status_code == 400
    ban = c.post(f"/api/v1/admin/users/{uid}/ban", json={"confirm": True, "reason": "spam"})
    assert ban.status_code == 200
    unban = c.post(f"/api/v1/admin/users/{uid}/unban", json={"confirm": True})
    assert unban.status_code == 200

