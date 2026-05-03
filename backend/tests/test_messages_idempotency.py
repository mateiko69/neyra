from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.deps import get_current_user, get_db
from app.api.v1.endpoints.messages import router as messages_router
from app.db.base import Base
import app.models  # noqa: F401
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


class _FakeRedis:
    def __init__(self):
        self._kv: dict[str, str] = {}

    def get(self, k: str):
        return self._kv.get(k)

    def set(self, k: str, v: str, ex: int | None = None, nx: bool = False):
        if nx and k in self._kv:
            return False
        self._kv[k] = str(v)
        return True


def _client(db: Session, current_user: User) -> TestClient:
    app = FastAPI()
    app.include_router(messages_router, prefix="/api/v1/messages")

    def _override_db():
        yield db

    def _override_user():
        return current_user

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_user] = _override_user
    return TestClient(app)


def test_messages_post_idempotency_key_returns_same_message(monkeypatch):
    db = _memory_db()
    try:
        a = User(email="a@example.com", hashed_password="x", is_active=True)
        b = User(email="b@example.com", hashed_password="x", is_active=True)
        db.add_all([a, b])
        db.flush()
        db.add(Profile(user_id=int(a.id), display_name="A", photo_urls="a.jpg", city="NYC", age=28))
        db.add(Profile(user_id=int(b.id), display_name="B", photo_urls="b.jpg", city="NYC", age=30))
        db.add(Match(user_a_id=int(a.id), user_b_id=int(b.id)))
        db.commit()

        fake = _FakeRedis()
        monkeypatch.setattr("app.api.v1.endpoints.messages.get_redis", lambda: fake)

        c = _client(db, a)
        payload = {
            "receiver_id": int(b.id),
            "content": "hello",
            "conversation_context": [],
            "idempotency_key": "k:123",
        }
        r1 = c.post("/api/v1/messages", json=payload)
        assert r1.status_code == 200
        d1 = r1.json()
        assert isinstance(d1, dict)
        assert int(d1.get("id") or 0) > 0

        r2 = c.post("/api/v1/messages", json=payload)
        assert r2.status_code == 200
        d2 = r2.json()
        assert int(d2.get("id") or 0) == int(d1.get("id") or 0)
    finally:
        db.close()

