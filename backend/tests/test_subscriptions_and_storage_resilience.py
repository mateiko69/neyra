"""Resilience: /subscriptions/me and local verification uploads must not 500 in production-like failures."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401 — register SQLAlchemy tables on Base.metadata

from app.api.deps import get_current_user, get_db
from app.api.v1.endpoints import subscriptions
from app.core.config import settings
from app.core.security import get_password_hash
from app.db.base import Base
from app.models.user import User
from app.services.storage.local_provider import LocalStorageProvider


def _memory_session() -> Session:
    engine = create_engine(
        "sqlite://",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return Session(engine)


def test_subscriptions_me_safe_json_when_service_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.api.v1.endpoints.subscriptions as submod

    db = _memory_session()
    try:
        u = User(email="subme@b.com", hashed_password=get_password_hash("x"), is_active=True)
        db.add(u)
        db.commit()

        def _boom(self, *a, **k):
            raise RuntimeError("simulated_db")

        monkeypatch.setattr(submod.SubscriptionService, "get_billing_plan", _boom)

        app = FastAPI()
        app.include_router(subscriptions.router, prefix="/api/v1/subscriptions")

        def _db():
            yield db

        def _user():
            return u

        app.dependency_overrides[get_db] = _db
        app.dependency_overrides[get_current_user] = _user

        client = TestClient(app)
        r = client.get("/api/v1/subscriptions/me")
        assert r.status_code == 200
        j = r.json()
        assert j.get("plan_code") == "free"
        assert j.get("billing_plan") == "free"
        assert j.get("status") == "inactive"
    finally:
        db.close()


def test_local_storage_writes_nested_verification_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    up = tmp_path / "uploads"
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(up))
    monkeypatch.setattr(settings, "LOCAL_UPLOAD_DIR", "uploads")
    provider = LocalStorageProvider()
    url = provider.save("verification/99_abcd1234.jpg", b"ok")
    assert (up / "verification" / "99_abcd1234.jpg").is_file()
    assert "/verification/" in url
