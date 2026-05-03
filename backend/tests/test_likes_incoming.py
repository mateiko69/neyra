from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.deps import get_current_user, get_db
from app.api.v1.endpoints.likes import router as likes_router
from app.db.base import Base
import app.models  # noqa: F401 — register IncomingLikeHide on Base.metadata
from app.models.incoming_like_hide import IncomingLikeHide
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
    app.include_router(likes_router, prefix="/api/v1/likes")

    def _override_db():
        yield db

    def _override_user():
        return current_user

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_user] = _override_user
    return TestClient(app)


def _mk_pair(db: Session) -> tuple[User, User]:
    a = User(email="viewer@example.com", hashed_password="x", is_active=True)
    b = User(email="admirer@example.com", hashed_password="x", is_active=True)
    db.add_all([a, b])
    db.flush()
    db.add(
        Profile(
            user_id=int(a.id),
            display_name="Viewer",
            photo_urls="a.jpg",
            city="NYC",
            age=28,
        )
    )
    db.add(
        Profile(
            user_id=int(b.id),
            display_name="Blair",
            photo_urls="b.jpg",
            city="NYC",
            age=30,
        )
    )
    db.commit()
    return a, b


def test_incoming_lists_admirer_and_masks_name_for_free():
    db = _memory_db()
    try:
        a, b = _mk_pair(db)
        db.add(Swipe(swiper_id=int(b.id), target_user_id=int(a.id), liked=True))
        db.commit()

        c = _client(db, a)
        r = c.get("/api/v1/likes/incoming?limit=10")
        assert r.status_code == 200
        body = r.json()
        assert body.get("waiting_count") == 1
        assert body.get("is_premium") is False
        items = body.get("items") or []
        assert len(items) == 1
        assert items[0].get("user_id") == int(b.id)
        assert items[0].get("preview_name") == "B****"
        assert items[0].get("distance") == 1
    finally:
        db.close()


def test_hide_removes_from_incoming_and_received():
    db = _memory_db()
    try:
        a, b = _mk_pair(db)
        db.add(Swipe(swiper_id=int(b.id), target_user_id=int(a.id), liked=True))
        db.commit()

        c = _client(db, a)
        h = c.post("/api/v1/likes/hide", json={"user_id": int(b.id)})
        assert h.status_code == 200
        assert h.json().get("ok") is True

        r = c.get("/api/v1/likes/incoming?limit=10")
        assert r.status_code == 200
        assert r.json().get("waiting_count") == 0
        assert (r.json().get("items") or []) == []

        rec = c.get("/api/v1/likes/received?limit=10")
        assert rec.status_code == 200
        assert rec.json().get("count") == 0
        assert (rec.json().get("likesReceived") or []) == []

        rows = db.query(IncomingLikeHide).filter(IncomingLikeHide.viewer_user_id == int(a.id)).all()
        assert len(rows) == 1
        assert int(rows[0].admirer_user_id) == int(b.id)
    finally:
        db.close()


def test_matched_admirer_not_listed():
    db = _memory_db()
    try:
        a, b = _mk_pair(db)
        db.add(Swipe(swiper_id=int(b.id), target_user_id=int(a.id), liked=True))
        ua, ub = sorted([int(a.id), int(b.id)])
        db.add(Match(user_a_id=ua, user_b_id=ub))
        db.commit()

        c = _client(db, a)
        r = c.get("/api/v1/likes/incoming?limit=10")
        assert r.status_code == 200
        assert r.json().get("waiting_count") == 0
    finally:
        db.close()


def test_reveal_free_returns_paywall_flag():
    db = _memory_db()
    try:
        a, b = _mk_pair(db)
        db.add(Swipe(swiper_id=int(b.id), target_user_id=int(a.id), liked=True))
        db.commit()

        c = _client(db, a)
        r = c.post("/api/v1/likes/reveal", json={"user_id": int(b.id)})
        assert r.status_code == 200
        assert r.json().get("ok") is False
        assert r.json().get("requires_premium") is True
    finally:
        db.close()
