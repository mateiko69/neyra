from __future__ import annotations

from datetime import UTC, datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.deps import get_db, get_current_user
from app.api.v1.endpoints.profiles import router as profiles_router
from app.core.config import settings
from app.db.base import Base
from app.models.oauth_account import OAuthAccount
from app.models.profile import Profile
from app.models.user import User
from seed import ensure_user


def _memory_db() -> Session:
    engine = create_engine(
        "sqlite://",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return Session(engine)


def test_seed_does_not_modify_google_oauth_users():
    settings.ENV = "test"
    db = _memory_db()
    try:
        user = User(email="taras@example.com", hashed_password=None, is_active=True)
        db.add(user)
        db.flush()
        db.add(OAuthAccount(user_id=int(user.id), provider="google", provider_user_id="sub-1", email_snapshot="taras@example.com"))
        profile = Profile(user_id=int(user.id), display_name="Real Taras", city="RealCity", bio="RealBio")
        db.add(profile)
        db.commit()

        _u2, p2 = ensure_user(
            db,
            datetime.now(UTC),
            email="taras@example.com",
            password="password123",
            name="Seed Taras",
            bio="SeedBio",
            age=29,
            city="Kyiv",
            gender="male",
            interested_in="female",
            relationship_goal="relationship",
            interests=["fitness"],
            lifestyle_tags=["confident"],
            photo_urls=["https://images.example.com/taras-1.jpg"],
        )
        assert p2.display_name == "Real Taras"
        assert p2.city == "RealCity"
        assert p2.bio == "RealBio"
    finally:
        db.close()


def test_seed_only_fills_empty_fields_for_demo_users():
    settings.ENV = "test"
    db = _memory_db()
    try:
        user = User(email="anna@example.com", hashed_password="x", is_active=True)
        db.add(user)
        db.flush()
        profile = Profile(user_id=int(user.id), display_name="Anna", city="CustomCity")
        db.add(profile)
        db.commit()

        _u2, p2 = ensure_user(
            db,
            datetime.now(UTC),
            email="anna@example.com",
            password="password123",
            name="Seed Anna",
            bio="SeedBio",
            age=25,
            city="Kyiv",
            gender="female",
            interested_in="male",
            relationship_goal="relationship",
            interests=["design"],
            lifestyle_tags=["creative"],
            photo_urls=["https://images.example.com/anna-1.jpg"],
        )
        # Existing non-empty values must remain untouched.
        assert p2.display_name == "Anna"
        assert p2.city == "CustomCity"
    finally:
        db.close()


def test_profile_patch_commits_changes():
    settings.ENV = "test"
    db = _memory_db()
    try:
        user = User(email="me@example.com", hashed_password="x", is_active=True)
        db.add(user)
        db.flush()
        profile = Profile(user_id=int(user.id), display_name="Me", bio="Old")
        db.add(profile)
        db.commit()

        app = FastAPI()
        app.include_router(profiles_router, prefix="/api/v1/profiles")

        def _override_db():
            yield db

        def _override_user():
            return user

        app.dependency_overrides[get_db] = _override_db
        app.dependency_overrides[get_current_user] = _override_user

        client = TestClient(app)
        r = client.patch("/api/v1/profiles/me", json={"bio": "New"})
        assert r.status_code == 200

        db.refresh(profile)
        assert profile.bio == "New"
    finally:
        db.close()


def test_startup_diagnostics_does_not_crash():
    # Importing the main app + creating a TestClient triggers startup events.
    settings.ENV = "test"
    from app.main import app as main_app  # noqa: WPS433

    client = TestClient(main_app)
    r = client.get("/health")
    assert r.status_code == 200

