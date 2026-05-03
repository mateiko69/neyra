from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.deps import get_current_user, get_db
from app.api.v1.endpoints.discover import router as discover_router
from app.core.config import settings
from app.db.base import Base
from app.models.profile import Profile
from app.models.user import User
from app.services.demo_mode import set_demo_mode_enabled


def _memory_db() -> Session:
    engine = create_engine(
        "sqlite://",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return Session(engine)


def test_discover_feed_excludes_admin_users(monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_EMAILS", "admin@example.com")
    db = _memory_db()
    try:
        viewer = User(email="viewer@example.com", hashed_password="x", is_active=True)
        admin = User(email="admin@example.com", hashed_password="x", is_active=True)
        normal = User(email="normal@example.com", hashed_password="x", is_active=True)
        db.add_all([viewer, admin, normal])
        db.flush()
        db.add(
            Profile(
                user_id=int(viewer.id),
                display_name="Viewer",
                photo_urls="x.jpg",
                onboarding_completed=True,
                gender="male",
                interested_in="women",
                age=28,
            )
        )
        db.add(
            Profile(
                user_id=int(admin.id),
                display_name="Admin",
                photo_urls="a.jpg",
                onboarding_completed=True,
                gender="female",
                interested_in="men",
                age=27,
            )
        )
        db.add(
            Profile(
                user_id=int(normal.id),
                display_name="Normal",
                photo_urls="n.jpg",
                onboarding_completed=True,
                gender="female",
                interested_in="men",
                age=26,
            )
        )
        db.commit()
        set_demo_mode_enabled(db, False)

        app = FastAPI()
        app.include_router(discover_router, prefix="/api/v1/discover")

        def _override_db():
            yield db

        def _override_user():
            return viewer

        app.dependency_overrides[get_db] = _override_db
        app.dependency_overrides[get_current_user] = _override_user

        client = TestClient(app)
        r = client.get("/api/v1/discover/feed?limit=20&offset=0")
        assert r.status_code == 200
        rows = r.json()
        ids = {int(x.get("user_id") or 0) for x in rows if isinstance(x, dict)}
        assert int(admin.id) not in ids
        assert int(normal.id) in ids
    finally:
        db.close()

