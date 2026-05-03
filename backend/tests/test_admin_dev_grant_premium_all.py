from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.deps import get_admin_user, get_admin_actor, get_db
from app.api.v1.endpoints.admin import router as admin_router
from app.core.config import settings
from app.db.base import Base
from app.models.user import User


def _memory_db() -> Session:
    engine = create_engine(
        "sqlite://",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return Session(engine)


def test_dev_grant_and_revoke_premium_all(monkeypatch):
    monkeypatch.setattr(settings, "ENV", "development")

    db = _memory_db()
    try:
        now = datetime.now(UTC)
        u1 = User(email="a@example.com", hashed_password="x", is_active=True, premium_until=None)
        u2 = User(email="b@example.com", hashed_password="x", is_active=True, premium_until=now - timedelta(days=1))
        u3 = User(email="c@example.com", hashed_password="x", is_active=True, premium_until=now + timedelta(days=10))
        db.add_all([u1, u2, u3])
        db.commit()

        app = FastAPI()
        app.include_router(admin_router, prefix="/api/v1/admin")

        def _override_db():
            yield db

        def _override_admin():
            # just needs to pass Depends(get_admin_user)
            return u1

        app.dependency_overrides[get_db] = _override_db
        app.dependency_overrides[get_admin_user] = _override_admin
        app.dependency_overrides[get_admin_actor] = _override_admin

        client = TestClient(app)

        r1 = client.post("/api/v1/admin/dev/grant-premium-all")
        assert r1.status_code == 200
        payload1 = r1.json()
        assert payload1["ok"] is True
        assert int(payload1["updated_users"]) == 2  # u1/u2 updated, u3 already premium

        db.refresh(u1)
        db.refresh(u2)
        db.refresh(u3)
        assert u1.premium_until is not None
        assert u2.premium_until is not None
        assert u3.premium_until is not None  # unchanged (still future)

        r2 = client.post("/api/v1/admin/dev/revoke-premium-all")
        assert r2.status_code == 200
        payload2 = r2.json()
        assert payload2["ok"] is True

        db.refresh(u1)
        db.refresh(u2)
        db.refresh(u3)
        assert u1.premium_until is None
        assert u2.premium_until is None
        assert u3.premium_until is None
    finally:
        db.close()


def test_dev_grant_aborts_in_production(monkeypatch):
    monkeypatch.setattr(settings, "ENV", "production")

    db = _memory_db()
    try:
        u1 = User(email="admin@example.com", hashed_password="x", is_active=True, premium_until=None)
        db.add(u1)
        db.commit()

        app = FastAPI()
        app.include_router(admin_router, prefix="/api/v1/admin")

        def _override_db():
            yield db

        def _override_admin():
            return u1

        app.dependency_overrides[get_db] = _override_db
        app.dependency_overrides[get_admin_user] = _override_admin
        app.dependency_overrides[get_admin_actor] = _override_admin

        client = TestClient(app)
        r = client.post("/api/v1/admin/dev/grant-premium-all")
        assert r.status_code == 403
    finally:
        db.close()

