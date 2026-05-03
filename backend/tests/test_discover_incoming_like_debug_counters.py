"""Regression: incoming-like candidates stay in Discover until mutual match; debug counters reflect that."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.deps import get_current_user, get_db
from app.api.v1.endpoints.discover import router as discover_router
from app.api.v1.endpoints.swipes import router as swipes_router
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


def _build_app(db: Session, holder: dict[str, User]) -> TestClient:
    app = FastAPI()
    app.include_router(discover_router, prefix="/api/v1/discover")
    app.include_router(swipes_router, prefix="/api/v1/swipes")

    def _override_db():
        yield db

    def _override_user():
        return holder["current"]

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_user] = _override_user
    return TestClient(app)


def _seed_pair(db: Session) -> tuple[User, User]:
    a = User(email="debug-counters-a@example.com", hashed_password="x", is_active=True)
    b = User(email="debug-counters-b@example.com", hashed_password="x", is_active=True)
    db.add_all([a, b])
    db.flush()
    db.add(
        Profile(
            user_id=int(a.id),
            display_name="A",
            gender="man",
            interested_in="women",
            age=28,
            min_preferred_age=18,
            max_preferred_age=80,
            photo_urls="a.jpg",
            onboarding_completed=True,
        )
    )
    db.add(
        Profile(
            user_id=int(b.id),
            display_name="B",
            gender="woman",
            interested_in="men",
            age=27,
            min_preferred_age=18,
            max_preferred_age=80,
            photo_urls="b.jpg",
            onboarding_completed=True,
        )
    )
    db.commit()
    return a, b


def test_discover_debug_counters_incoming_like_until_match(monkeypatch):
    monkeypatch.setattr(settings, "DEV_TOOLS_ENABLED", True)
    db = _memory_db()
    try:
        set_demo_mode_enabled(db, False)
        a, b = _seed_pair(db)
        holder: dict[str, User] = {"current": a}
        client = _build_app(db, holder)

        holder["current"] = a
        assert client.post("/api/v1/swipes", json={"target_user_id": int(b.id), "liked": True}).status_code == 200

        holder["current"] = b
        r1 = client.get("/api/v1/discover/feed?limit=20&offset=0&include_debug=true")
        assert r1.status_code == 200
        body1 = r1.json()
        assert isinstance(body1, dict)
        feed1 = body1.get("feed") or []
        dbg1 = body1.get("debug") or {}
        ids1 = [int(x.get("user_id") or 0) for x in feed1 if isinstance(x, dict)]
        assert int(a.id) in ids1
        assert int(dbg1.get("incoming_like_candidates_included") or 0) >= 1
        assert int(dbg1.get("incoming_like_candidates_excluded") or 0) == 0

        assert client.post("/api/v1/swipes", json={"target_user_id": int(a.id), "liked": True}).status_code == 200

        r2 = client.get("/api/v1/discover/feed?limit=20&offset=0&include_debug=true")
        assert r2.status_code == 200
        body2 = r2.json()
        assert isinstance(body2, dict)
        feed2 = body2.get("feed") or []
        dbg2 = body2.get("debug") or {}
        ids2 = [int(x.get("user_id") or 0) for x in feed2 if isinstance(x, dict)]
        assert int(a.id) not in ids2
        assert int(dbg2.get("filtered_by_match") or 0) >= 1
    finally:
        db.close()
