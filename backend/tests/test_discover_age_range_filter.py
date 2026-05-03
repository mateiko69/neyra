from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.deps import get_current_user, get_db
from app.api.v1.endpoints.discover import router as discover_router
from app.db.base import Base
from app.models.profile import Profile
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


def _client(db: Session, current_user: User) -> TestClient:
    app = FastAPI()
    app.include_router(discover_router, prefix="/api/v1/discover")

    def _override_db():
        yield db

    def _override_user():
        return current_user

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_user] = _override_user
    return TestClient(app)


def test_discover_feed_filters_by_viewer_age_range_when_set():
    db = _memory_db()
    try:
        viewer = User(email="viewer@example.com", hashed_password="x", is_active=True)
        inside = User(email="inside@example.com", hashed_password="x", is_active=True)
        outside = User(email="outside@example.com", hashed_password="x", is_active=True)
        db.add_all([viewer, inside, outside])
        db.flush()

        db.add(
            Profile(
                user_id=int(viewer.id),
                display_name="Viewer",
                gender="woman",
                interested_in="men",
                min_preferred_age=25,
                max_preferred_age=30,
                photo_urls="v.jpg",
                age=26,
                city="Kyiv",
                native_language="uk",
                relationship_goal="dating",
                onboarding_completed=True,
            )
        )
        db.add(
            Profile(
                user_id=int(inside.id),
                display_name="Inside",
                gender="man",
                interested_in="women",
                photo_urls="i.jpg",
                age=28,
                city="Kyiv",
                bio="hi",
                onboarding_completed=True,
            )
        )
        db.add(
            Profile(
                user_id=int(outside.id),
                display_name="Outside",
                gender="man",
                interested_in="women",
                photo_urls="o.jpg",
                age=40,
                city="Kyiv",
                bio="hi",
                onboarding_completed=True,
            )
        )
        db.commit()

        c = _client(db, viewer)
        r = c.get("/api/v1/discover/feed?limit=50")
        assert r.status_code == 200
        ids = {int(card.get("user_id") or 0) for card in (r.json() or []) if isinstance(card, dict)}
        assert int(inside.id) in ids
        assert int(outside.id) not in ids
    finally:
        db.close()

