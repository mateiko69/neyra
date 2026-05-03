from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.deps import get_db
from app.api.v1.endpoints.auth_social import router as auth_social_router
from app.api.v1.endpoints.profiles import router as profiles_router
from app.core.config import settings
from app.db.base import Base


def _memory_db() -> Session:
    engine = create_engine(
        "sqlite://",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return Session(engine)


def _build_client(db: Session) -> TestClient:
    app = FastAPI()
    app.include_router(auth_social_router, prefix="/api/v1/auth")
    app.include_router(profiles_router, prefix="/api/v1/profiles")

    def _override_db():
        yield db

    app.dependency_overrides[get_db] = _override_db
    return TestClient(app)


def test_google_oauth_login_is_idempotent_and_does_not_reset_profile(monkeypatch):
    # Enable dev social mock so we can simulate Google without external calls.
    monkeypatch.setattr(settings, "AUTH_DEV_SOCIAL", True)
    monkeypatch.setattr(settings, "ENV", "test")

    db = _memory_db()
    try:
        client = _build_client(db)

        # 1) First Google login
        r1 = client.post("/api/v1/auth/social/dev/google")
        assert r1.status_code == 200
        token1 = r1.json()["access_token"]
        headers = {"Authorization": f"Bearer {token1}"}

        # 2) User fills onboarding/profile via PUT (simulate partial client payload)
        put_payload = {
            "display_name": "Dev Google",
            "gender": "male",
            "interested_in": "female",
            "age": 25,
            "city": "Kyiv",
            "native_language": "en",
            "relationship_goal": "dating",
            "vibe": "warm",
            "bio": "Hello world",
            "interests": "music,travel",
            "min_preferred_age": 23,
            "max_preferred_age": 35,
            # Provide photos to satisfy onboarding gating in profile_needs_onboarding().
            "photo_urls": "https://cdn.example.com/me.jpg",
        }
        r_put = client.put("/api/v1/profiles/me", json=put_payload, headers=headers)
        assert r_put.status_code == 200

        me1 = client.get("/api/v1/profiles/me", headers=headers)
        assert me1.status_code == 200
        p1 = me1.json()
        assert p1["display_name"] == "Dev Google"
        assert p1["gender"] == "male"
        assert p1["interested_in"] == "women"
        assert p1["city"] == "Kyiv"
        assert p1["bio"] == "Hello world"
        assert p1["min_preferred_age"] == 23
        assert p1["max_preferred_age"] == 35
        assert (p1.get("photo_urls") or "").strip() != ""

        # 3) Second Google login with same provider_user_id must reuse the same user/profile
        r2 = client.post("/api/v1/auth/social/dev/google")
        assert r2.status_code == 200
        assert r2.json().get("redirect_path") != "/onboarding"
        token2 = r2.json()["access_token"]
        headers2 = {"Authorization": f"Bearer {token2}"}

        # 4) Profile data must still be present (not reset/overwritten)
        me2 = client.get("/api/v1/profiles/me", headers=headers2)
        assert me2.status_code == 200
        p2 = me2.json()
        assert p2["display_name"] == "Dev Google"
        assert p2["gender"] == "male"
        assert p2["interested_in"] == "women"
        assert p2["city"] == "Kyiv"
        assert p2["bio"] == "Hello world"
        assert p2["min_preferred_age"] == 23
        assert p2["max_preferred_age"] == 35
        assert (p2.get("photo_urls") or "").strip() != ""
    finally:
        db.close()

