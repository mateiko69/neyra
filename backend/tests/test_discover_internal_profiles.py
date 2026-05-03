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


def _seed_complete_profile(
    db: Session,
    *,
    email: str,
    name: str,
    gender: str,
    interested_in: str,
    viewer_gender: str,
    viewer_interested: str,
) -> tuple[User, User]:
    viewer = User(email="viewer_real@example.com", hashed_password="x", is_active=True)
    cand = User(email=email, hashed_password="x", is_active=True)
    db.add_all([viewer, cand])
    db.flush()
    db.add(
        Profile(
            user_id=int(viewer.id),
            display_name="Viewer Real",
            photo_urls="v.jpg",
            onboarding_completed=True,
            gender=viewer_gender,
            interested_in=viewer_interested,
            age=30,
        )
    )
    db.add(
        Profile(
            user_id=int(cand.id),
            display_name=name,
            photo_urls="c.jpg",
            onboarding_completed=True,
            gender=gender,
            interested_in=interested_in,
            age=28,
        )
    )
    db.commit()
    return viewer, cand


def test_qa_profile_hidden_from_discover(monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_EMAILS", "")
    db = _memory_db()
    try:
        viewer, cand = _seed_complete_profile(
            db,
            email="qa_adam@example.com",
            name="QA Adam",
            gender="female",
            interested_in="men",
            viewer_gender="male",
            viewer_interested="women",
        )
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
        r = client.get("/api/v1/discover/feed?limit=20")
        assert r.status_code == 200
        rows = r.json()
        ids = {int(x.get("user_id") or 0) for x in rows if isinstance(x, dict)}
        assert int(cand.id) not in ids
    finally:
        db.close()


def test_normal_profiles_still_visible(monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_EMAILS", "")
    db = _memory_db()
    try:
        viewer, cand = _seed_complete_profile(
            db,
            email="jane_normal@example.com",
            name="Jane",
            gender="female",
            interested_in="men",
            viewer_gender="male",
            viewer_interested="women",
        )
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
        r = client.get("/api/v1/discover/feed?limit=20")
        assert r.status_code == 200
        rows = r.json()
        ids = {int(x.get("user_id") or 0) for x in rows if isinstance(x, dict)}
        assert int(cand.id) in ids
    finally:
        db.close()


def test_admin_email_profile_hidden(monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_EMAILS", "boss@example.com")
    db = _memory_db()
    try:
        viewer = User(email="viewer_real@example.com", hashed_password="x", is_active=True)
        admin_u = User(email="boss@example.com", hashed_password="x", is_active=True)
        db.add_all([viewer, admin_u])
        db.flush()
        db.add(
            Profile(
                user_id=int(viewer.id),
                display_name="Viewer Real",
                photo_urls="v.jpg",
                onboarding_completed=True,
                gender="male",
                interested_in="women",
                age=30,
            )
        )
        db.add(
            Profile(
                user_id=int(admin_u.id),
                display_name="Admin Person",
                photo_urls="a.jpg",
                onboarding_completed=True,
                gender="female",
                interested_in="men",
                age=29,
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
        r = client.get("/api/v1/discover/feed?limit=20")
        assert r.status_code == 200
        rows = r.json()
        ids = {int(x.get("user_id") or 0) for x in rows if isinstance(x, dict)}
        assert int(admin_u.id) not in ids
    finally:
        db.close()
