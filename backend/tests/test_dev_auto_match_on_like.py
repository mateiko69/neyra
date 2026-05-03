from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.deps import get_current_user, get_db
from app.api.v1.endpoints.swipes import router as swipes_router
from app.core.config import settings
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


def _build_client(db: Session, current_user: User) -> TestClient:
    app = FastAPI()
    app.include_router(swipes_router, prefix="/api/v1/swipes")

    def _override_db():
        yield db

    def _override_user():
        return current_user

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_user] = _override_user
    return TestClient(app)


def test_like_auto_matches_in_development(monkeypatch):
    monkeypatch.setattr(settings, "ENV", "development")
    db = _memory_db()
    try:
        me = User(email="me@example.com", hashed_password="x", is_active=True)
        them = User(email="them@example.com", hashed_password="x", is_active=True)
        db.add_all([me, them])
        db.flush()
        db.add(Profile(user_id=int(me.id), display_name="Me", photo_urls="x.jpg"))
        db.add(Profile(user_id=int(them.id), display_name="Them", photo_urls="y.jpg"))
        db.commit()

        client = _build_client(db, me)
        r = client.post("/api/v1/swipes", json={"target_user_id": int(them.id), "liked": True})
        assert r.status_code == 200
        payload = r.json()
        assert payload.get("matched") is False

        # No reciprocal swipe created automatically.
        recip = db.query(Swipe).filter(Swipe.swiper_id == int(them.id), Swipe.target_user_id == int(me.id)).first()
        assert recip is None

        # No match created on one-sided like.
        a, b = sorted([int(me.id), int(them.id)])
        m = db.query(Match).filter(Match.user_a_id == a, Match.user_b_id == b).first()
        assert m is None
    finally:
        db.close()


def test_like_does_not_auto_match_in_production(monkeypatch):
    monkeypatch.setattr(settings, "ENV", "production")
    db = _memory_db()
    try:
        me = User(email="me2@example.com", hashed_password="x", is_active=True)
        them = User(email="them2@example.com", hashed_password="x", is_active=True)
        db.add_all([me, them])
        db.flush()
        db.add(Profile(user_id=int(me.id), display_name="Me", photo_urls="x.jpg"))
        db.add(Profile(user_id=int(them.id), display_name="Them", photo_urls="y.jpg"))
        db.commit()

        client = _build_client(db, me)
        r = client.post("/api/v1/swipes", json={"target_user_id": int(them.id), "liked": True})
        assert r.status_code == 200
        payload = r.json()
        assert payload.get("matched") is False
    finally:
        db.close()

