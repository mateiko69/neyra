from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.deps import get_current_user, get_db
from app.api.v1.endpoints.swipes import router as swipes_router
from app.db.base import Base
from app.models.match import Match
from app.models.profile import Profile
from app.models.swipe import Swipe
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

    def _override_db():
        yield db

    def _override_user():
        return current_user

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_user] = _override_user
    return TestClient(app)


def _mk_users(db: Session) -> tuple[User, User]:
    a = User(email="a@example.com", hashed_password="x", is_active=True)
    b = User(email="b@example.com", hashed_password="x", is_active=True)
    db.add_all([a, b])
    db.flush()
    db.add(Profile(user_id=int(a.id), display_name="A", photo_urls="a.jpg"))
    db.add(Profile(user_id=int(b.id), display_name="B", photo_urls="b.jpg"))
    db.commit()
    return a, b


def test_a_likes_b_no_match():
    db = _memory_db()
    try:
        a, b = _mk_users(db)
        c = _client(db, a)
        r = c.post("/api/v1/swipes", json={"target_user_id": int(b.id), "liked": True})
        assert r.status_code == 200
        assert r.json().get("matched") is False
        a_id, b_id = sorted([int(a.id), int(b.id)])
        assert db.query(Match).filter(Match.user_a_id == a_id, Match.user_b_id == b_id).first() is None
    finally:
        db.close()


def test_b_likes_a_after_a_liked_b_creates_match():
    db = _memory_db()
    try:
        a, b = _mk_users(db)
        c_a = _client(db, a)
        r1 = c_a.post("/api/v1/swipes", json={"target_user_id": int(b.id), "liked": True})
        assert r1.status_code == 200
        assert r1.json().get("matched") is False

        c_b = _client(db, b)
        r2 = c_b.post("/api/v1/swipes", json={"target_user_id": int(a.id), "liked": True})
        assert r2.status_code == 200
        assert r2.json().get("matched") is True

        a_id, b_id = sorted([int(a.id), int(b.id)])
        assert db.query(Match).filter(Match.user_a_id == a_id, Match.user_b_id == b_id).first() is not None
    finally:
        db.close()


def test_duplicate_likes_are_idempotent():
    db = _memory_db()
    try:
        a, b = _mk_users(db)
        c = _client(db, a)
        r1 = c.post("/api/v1/swipes", json={"target_user_id": int(b.id), "liked": True})
        assert r1.status_code == 200
        r2 = c.post("/api/v1/swipes", json={"target_user_id": int(b.id), "liked": True})
        assert r2.status_code == 200
        assert db.query(Swipe).filter(Swipe.swiper_id == int(a.id), Swipe.target_user_id == int(b.id)).count() == 1
    finally:
        db.close()


def test_match_creation_is_idempotent():
    db = _memory_db()
    try:
        a, b = _mk_users(db)
        c_a = _client(db, a)
        c_b = _client(db, b)
        c_a.post("/api/v1/swipes", json={"target_user_id": int(b.id), "liked": True})
        r = c_b.post("/api/v1/swipes", json={"target_user_id": int(a.id), "liked": True})
        assert r.status_code == 200
        assert r.json().get("matched") is True

        # Repeat B like again should not create a second Match.
        c_b.post("/api/v1/swipes", json={"target_user_id": int(a.id), "liked": True})
        a_id, b_id = sorted([int(a.id), int(b.id)])
        assert db.query(Match).filter(Match.user_a_id == a_id, Match.user_b_id == b_id).count() == 1
    finally:
        db.close()

