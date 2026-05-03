from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.deps import get_current_user, get_db
from app.api.v1.endpoints.likes import router as likes_router
from app.api.v1.endpoints.profiles import router as profiles_router
from app.api.v1.endpoints.swipes import router as swipes_router
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
    app.include_router(swipes_router, prefix="/api/v1/swipes")
    app.include_router(likes_router, prefix="/api/v1/likes")
    app.include_router(profiles_router, prefix="/api/v1/profiles")

    def _override_db():
        yield db

    def _override_user():
        return current_user

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_user] = _override_user
    return TestClient(app)


def test_likes_reveal_like_back_creates_match_and_partner_profile_is_accessible(monkeypatch):
    db = _memory_db()
    try:
        a = User(email="a@example.com", hashed_password="x", is_active=True)
        b = User(email="b@example.com", hashed_password="x", is_active=True)
        db.add_all([a, b])
        db.flush()
        db.add(Profile(user_id=int(a.id), display_name="A", photo_urls="a.jpg", age=25, onboarding_completed=True))
        db.add(Profile(user_id=int(b.id), display_name="B", photo_urls="b.jpg", age=25, onboarding_completed=True))
        db.commit()

        # A likes B
        c_a = _client(db, a)
        r_like = c_a.post("/api/v1/swipes", json={"target_user_id": int(b.id), "liked": True})
        assert r_like.status_code == 200

        # B sees A in incoming likes
        c_b = _client(db, b)
        r_in = c_b.get("/api/v1/likes/incoming?limit=48")
        assert r_in.status_code == 200
        items = (r_in.json() or {}).get("items") or []
        assert any(int(x.get("user_id") or 0) == int(a.id) for x in items if isinstance(x, dict))

        # B reveals A (premium gating is out of scope for this test; force premium by monkeypatching)
        import app.api.v1.endpoints.likes as likes_mod

        monkeypatch.setattr(likes_mod, "_premium_flags", lambda _db, _u: (True, False))
        r_rev = c_b.post("/api/v1/likes/reveal", json={"user_id": int(a.id)})
        assert r_rev.status_code == 200
        assert r_rev.json().get("ok") is True

        # Partner profile must be accessible due to incoming like (no 403).
        r_partner = c_b.get(f"/api/v1/profiles/partner/{int(a.id)}")
        assert r_partner.status_code == 200
        assert int(r_partner.json().get("user_id") or 0) == int(a.id)

        # B likes back via /likes/respond and match is created
        r_resp = c_b.post("/api/v1/likes/respond", json={"user_id": int(a.id), "action": "like"})
        assert r_resp.status_code == 200
        j = r_resp.json()
        assert j.get("ok") is True
        assert j.get("matched") is True
        assert isinstance(j.get("match_id"), int)
        assert isinstance(j.get("chat_url"), str) and str(j.get("chat_url")).startswith("/chat/")
    finally:
        db.close()

