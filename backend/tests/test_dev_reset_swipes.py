from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.deps import get_current_user, get_db
from app.api.v1.endpoints.dev import router as dev_router
from app.core.config import settings
from app.db.base import Base
from app.models.match import Match
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


def test_reset_swipes_requires_flag(monkeypatch):
    monkeypatch.setattr(settings, "DEV_TOOLS_ENABLED", False)
    db = _memory_db()
    try:
        u = User(email="u@example.com", hashed_password="x", is_active=True)
        db.add(u)
        db.commit()
        db.refresh(u)

        app = FastAPI()
        app.include_router(dev_router, prefix="/api/v1/dev")

        def _override_db():
            yield db

        app.dependency_overrides[get_db] = _override_db
        app.dependency_overrides[get_current_user] = lambda: u

        c = TestClient(app)
        r = c.post("/api/v1/dev/reset-swipes")
        assert r.status_code == 403
    finally:
        db.close()


def test_reset_swipes_deletes_my_swipes_and_matches(monkeypatch):
    monkeypatch.setattr(settings, "DEV_TOOLS_ENABLED", True)
    db = _memory_db()
    try:
        a = User(email="a@example.com", hashed_password="x", is_active=True)
        b = User(email="b@example.com", hashed_password="x", is_active=True)
        db.add_all([a, b])
        db.flush()
        db.add(Swipe(swiper_id=int(a.id), target_user_id=int(b.id), liked=True))
        db.add(Swipe(swiper_id=int(b.id), target_user_id=int(a.id), liked=True))
        db.add(Match(user_a_id=int(a.id), user_b_id=int(b.id)))
        db.commit()

        app = FastAPI()
        app.include_router(dev_router, prefix="/api/v1/dev")
        def _override_db():
            yield db

        app.dependency_overrides[get_db] = _override_db
        app.dependency_overrides[get_current_user] = lambda: a
        c = TestClient(app)

        r = c.post("/api/v1/dev/reset-swipes")
        assert r.status_code == 200
        j = r.json()
        assert j["ok"] is True
        assert db.query(Swipe).count() == 0
        assert db.query(Match).count() == 0
    finally:
        db.close()

