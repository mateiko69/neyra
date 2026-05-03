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
import app.models  # noqa: F401
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


def test_discover_feed_blocked_when_viewer_onboarding_incomplete(monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_EMAILS", "")
    db = _memory_db()
    try:
        viewer = User(email="viewer@example.com", hashed_password="x", is_active=True)
        db.add(viewer)
        db.flush()
        db.add(
            Profile(
                user_id=int(viewer.id),
                display_name="Viewer",
                photo_urls="x.jpg",
                onboarding_completed=False,
                gender="",
                interested_in="",
                age=None,
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
        r = client.get("/api/v1/discover/feed?limit=12")
        assert r.status_code == 200
        body = r.json()
        assert body.get("onboarding_required") is True
        assert body.get("feed") == []
        assert "gender" in (body.get("missing_fields") or [])
    finally:
        db.close()
