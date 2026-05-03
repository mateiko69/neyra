from __future__ import annotations

from datetime import UTC, datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.deps import get_current_user, get_db
from app.api.v1.endpoints import admin as admin_mod
from app.api.v1.endpoints import profiles as profiles_mod
from app.db.base import Base
from app.models.profile import Profile
from app.models.user import User
from app.services.demo_mode import build_demo_reply


class DummyUser:
    def __init__(self, user_id: int):
        self.id = int(user_id)
        self.email = f"u{user_id}@example.com"


def _memory_db() -> Session:
    engine = create_engine(
        "sqlite://",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return Session(engine)


def _profiles_client(db: Session, uid: int) -> TestClient:
    app = FastAPI()
    app.include_router(profiles_mod.router, prefix="/api/v1/profiles")

    def _db():
        yield db

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_current_user] = lambda: DummyUser(uid)
    return TestClient(app)


def _admin_client(db: Session) -> TestClient:
    app = FastAPI()
    app.include_router(admin_mod.router, prefix="/api/v1/admin")

    class DummyAdmin:
        id = 999
        email = "admin@example.com"

    from app.api.deps import get_admin_actor, get_admin_user

    def _db():
        yield db

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_admin_user] = lambda: DummyAdmin()
    app.dependency_overrides[get_admin_actor] = lambda: DummyAdmin()
    return TestClient(app)


def test_founder_welcome_show_once_until_seen():
    db = _memory_db()
    try:
        db.add(User(id=1, email="a@example.com", hashed_password="x", is_active=True))
        db.add(
            Profile(
                user_id=1,
                display_name="A",
                photo_urls="https://x.example/a.jpg",
                bio="bio bio bio bio bio",
                onboarding_completed=True,
                founder_welcome_seen=False,
            )
        )
        db.commit()
        c = _profiles_client(db, 1)
        r1 = c.get("/api/v1/profiles/founder-welcome")
        assert r1.status_code == 200
        assert r1.json().get("show") is True
        r2 = c.post("/api/v1/profiles/founder-welcome/seen", json={})
        assert r2.status_code == 200
        r3 = c.get("/api/v1/profiles/founder-welcome")
        assert r3.json().get("show") is False
        assert r3.json().get("founder_welcome_seen") is True
    finally:
        db.close()


def test_demo_simulated_reply_labels_not_real_person():
    p = Profile(display_name="Maya")
    out = build_demo_reply(p, "hello", [])
    low = out.lower()
    assert "demo" in low
    assert "not a real person" in low


def test_admin_overview_excludes_demo_users_from_totals():
    db = _memory_db()
    try:
        now = datetime.now(UTC)
        db.add(
            User(
                id=1,
                email="real@example.com",
                hashed_password="x",
                is_active=True,
                is_demo=False,
                created_at=now,
                last_active_at=now,
            )
        )
        db.add(
            User(
                id=2,
                email="demo@example.com",
                hashed_password="x",
                is_active=True,
                is_demo=True,
                created_at=now,
                last_active_at=now,
            )
        )
        db.add(
            Profile(
                user_id=1,
                display_name="Real",
                photo_urls="https://x.example/a.jpg",
                bio="bio bio bio bio bio",
                is_demo_profile=False,
                onboarding_completed=True,
            )
        )
        db.add(
            Profile(
                user_id=2,
                display_name="Demo",
                photo_urls="https://x.example/b.jpg",
                bio="bio bio bio bio bio",
                is_demo_profile=True,
                onboarding_completed=True,
            )
        )
        db.commit()
        ac = _admin_client(db)
        res = ac.get("/api/v1/admin/stats/overview?period=today")
        assert res.status_code == 200
        body = res.json()
        assert body["users"]["total"] == 1
        assert body["users"]["active"] == 1
    finally:
        db.close()
