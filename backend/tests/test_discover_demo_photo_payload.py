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


def _build_client(db: Session, holder: dict[str, User]) -> TestClient:
    app = FastAPI()
    app.include_router(discover_router, prefix="/api/v1/discover")

    def _db():
        yield db

    def _user():
        return holder["current"]

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_current_user] = _user
    return TestClient(app)


def test_discover_demo_cards_always_include_primary_photo_fields():
    db = _memory_db()
    try:
        viewer = User(email="viewer@demo.test", hashed_password="x", is_active=True)
        demo = User(email="demo+woman_demo_014@neyra.local", hashed_password="x", is_active=True, is_demo=True)
        db.add_all([viewer, demo])
        db.flush()

        db.add(
            Profile(
                user_id=int(viewer.id),
                display_name="Viewer",
                gender="man",
                interested_in="women",
                age=28,
                min_preferred_age=18,
                max_preferred_age=80,
                onboarding_completed=True,
                photo_urls="/demo-profiles/men/demo_001/main.jpg",
            )
        )
        # Intentionally blank photo_urls to validate backend fallback guarantees.
        db.add(
            Profile(
                user_id=int(demo.id),
                display_name="Demo 14",
                gender="woman",
                interested_in="men",
                age=25,
                is_demo_profile=True,
                onboarding_completed=True,
                photo_urls="",
            )
        )
        db.commit()

        holder = {"current": viewer}
        client = _build_client(db, holder)
        r = client.get("/api/v1/discover/feed?limit=20&offset=0")
        assert r.status_code == 200
        rows = r.json() or []
        assert isinstance(rows, list)
        demo_card = next((x for x in rows if int(x.get("user_id") or 0) == int(demo.id)), None)
        assert isinstance(demo_card, dict)
        assert bool(demo_card.get("is_demo_profile")) is True
        photo_urls = demo_card.get("photo_urls") or []
        assert isinstance(photo_urls, list) and len(photo_urls) >= 1
        assert str(photo_urls[0]).startswith("/demo-profiles/")
        assert str(demo_card.get("primary_photo_url") or "").startswith("/demo-profiles/")
        assert str(demo_card.get("photo_url") or "").startswith("/demo-profiles/")
        assert str(demo_card.get("image_url") or "").startswith("/demo-profiles/")
        photos = demo_card.get("photos") or []
        assert isinstance(photos, list) and len(photos) >= 1
        assert str((photos[0] or {}).get("url") or "").startswith("/demo-profiles/")
    finally:
        db.close()

