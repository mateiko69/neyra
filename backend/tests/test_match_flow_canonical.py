from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.deps import get_current_user, get_db
from app.api.v1.endpoints.likes import router as likes_router
from app.api.v1.endpoints.matches import router as matches_router
from app.api.v1.endpoints.messages import router as messages_router
from app.api.v1.endpoints.nav import router as nav_router
from app.api.v1.endpoints.swipes import router as swipes_router
from app.db.base import Base
from app.models.match import Match
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


def _client(db: Session, user: User) -> TestClient:
    app = FastAPI()
    app.include_router(swipes_router, prefix="/api/v1/swipes")
    app.include_router(likes_router, prefix="/api/v1/likes")
    app.include_router(matches_router, prefix="/api/v1/matches")
    app.include_router(messages_router, prefix="/api/v1/messages")
    app.include_router(nav_router, prefix="/api/v1/nav")

    def _db():
        yield db

    def _user():
        return user

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_current_user] = _user
    return TestClient(app)


def test_mutual_like_always_creates_single_match():
    db = _memory_db()
    try:
        a = User(email="ma@example.com", hashed_password="x", is_active=True)
        b = User(email="mb@example.com", hashed_password="x", is_active=True)
        db.add_all([a, b])
        db.flush()
        db.add(Profile(user_id=int(a.id), display_name="A", photo_urls="a.jpg", age=25, onboarding_completed=True))
        db.add(Profile(user_id=int(b.id), display_name="B", photo_urls="b.jpg", age=26, onboarding_completed=True))
        db.commit()

        c_a = _client(db, a)
        r1 = c_a.post("/api/v1/swipes", json={"target_user_id": int(b.id), "liked": True})
        assert r1.status_code == 200
        assert r1.json().get("matched") is False

        c_b = _client(db, b)
        r2 = c_b.post("/api/v1/swipes", json={"target_user_id": int(a.id), "liked": True})
        assert r2.status_code == 200
        assert r2.json().get("matched") is True
        mid = int(r2.json().get("match_id"))
        assert mid > 0

        rows = db.query(Match).all()
        assert len(rows) == 1
        assert int(rows[0].id) == mid

        r_dup = c_b.post("/api/v1/swipes", json={"target_user_id": int(a.id), "liked": True})
        assert r_dup.status_code == 200
        assert db.query(Match).count() == 1
    finally:
        db.close()


def test_likes_respond_like_creates_match_and_lists():
    db = _memory_db()
    try:
        a = User(email="la@example.com", hashed_password="x", is_active=True)
        b = User(email="lb@example.com", hashed_password="x", is_active=True)
        db.add_all([a, b])
        db.flush()
        db.add(Profile(user_id=int(a.id), display_name="A", photo_urls="a.jpg", age=25, onboarding_completed=True))
        db.add(Profile(user_id=int(b.id), display_name="B", photo_urls="b.jpg", age=26, onboarding_completed=True))
        db.commit()

        c_a = _client(db, a)
        assert c_a.post("/api/v1/swipes", json={"target_user_id": int(b.id), "liked": True}).status_code == 200

        c_b = _client(db, b)
        r_resp = c_b.post("/api/v1/likes/respond", json={"user_id": int(a.id), "action": "like"})
        assert r_resp.status_code == 200
        body = r_resp.json()
        assert body.get("matched") is True
        assert isinstance(body.get("match_id"), int)
        assert body.get("conversation_id") == int(a.id)

        rm = c_b.get("/api/v1/matches")
        assert rm.status_code == 200
        arr = rm.json()
        assert isinstance(arr, list) and len(arr) == 1
        assert arr[0].get("partner_user_id") == int(a.id)
        assert arr[0].get("conversation_id") == int(a.id)
        assert "partner_photo" in arr[0]
        assert arr[0].get("last_message_preview") is None or isinstance(arr[0].get("last_message_preview"), str)

        badges = c_b.get("/api/v1/nav/badges")
        assert badges.status_code == 200
        bj = badges.json()
        assert int(bj.get("matches") or 0) >= 1
        assert "incoming_likes" in bj
        assert "matches_attention" in bj
    finally:
        db.close()
