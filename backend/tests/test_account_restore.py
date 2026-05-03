from datetime import UTC, datetime, timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.deps import get_current_user, get_db
from app.api.v1.endpoints.account import router as account_router
from app.core.security import get_password_hash
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


def _build_client(db: Session, user: User) -> TestClient:
    app = FastAPI()
    app.include_router(account_router, prefix="/api/v1")

    def _override_db():
        yield db

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


def test_restore_within_window_clears_deleted_flags():
    db = _memory_db()
    try:
        now = datetime.now(UTC)
        u = User(
            id=1,
            email="a@example.com",
            hashed_password=get_password_hash("pw123456"),
            is_active=True,
            is_deleted=True,
            deleted_at=now,
            deletion_scheduled_for=now + timedelta(days=30),
            matches_last_seen_at=now,
        )
        db.add(u)
        db.add(Profile(user_id=1, display_name="A"))
        db.commit()

        client = _build_client(db, u)
        res = client.request("POST", "/api/v1/account/restore", json={"confirm": True})
        assert res.status_code == 200
        assert res.json().get("ok") is True
        assert res.json().get("restored") is True

        user = db.query(User).filter(User.id == 1).first()
        assert user is not None
        assert user.is_deleted is False
        assert user.deleted_at is None
        assert user.deletion_scheduled_for is None
    finally:
        db.close()


def test_restore_after_window_returns_410():
    db = _memory_db()
    try:
        now = datetime.now(UTC)
        u = User(
            id=1,
            email="a@example.com",
            hashed_password=get_password_hash("pw123456"),
            is_active=True,
            is_deleted=True,
            deleted_at=now - timedelta(days=31),
            deletion_scheduled_for=now - timedelta(seconds=1),
            matches_last_seen_at=now,
        )
        db.add(u)
        db.add(Profile(user_id=1, display_name="A"))
        db.commit()

        client = _build_client(db, u)
        res = client.request("POST", "/api/v1/account/restore", json={"confirm": True})
        assert res.status_code == 410
    finally:
        db.close()

