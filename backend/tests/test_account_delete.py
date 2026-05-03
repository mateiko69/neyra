from datetime import UTC, datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.deps import get_current_user, get_db
from app.api.v1.endpoints.account import router as account_router
from app.core.security import get_password_hash
from app.db.base import Base
from app.models.analytics_event import AnalyticsEvent
from app.models.message import Message
from app.models.profile import Profile
from app.models.subscription import Subscription
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


def test_account_delete_soft_deletes_user_and_keeps_rows():
    db = _memory_db()
    try:
        u = User(
            id=1,
            email="a@example.com",
            hashed_password=get_password_hash("pw123456"),
            is_active=True,
            matches_last_seen_at=datetime.now(UTC),
        )
        db.add(u)
        db.add(Profile(user_id=1, display_name="A", photo_urls="/uploads/1_x.jpg"))
        db.add(Message(sender_id=1, receiver_id=1, content="self"))
        db.add(Subscription(user_id=1, provider="mock", status="active", plan_code="premium"))
        db.add(AnalyticsEvent(user_id=1, name="x", payload_json="{}"))
        db.commit()

        client = _build_client(db, u)
        res = client.request("DELETE", "/api/v1/account", json={"confirm": True, "password": "pw123456"})
        assert res.status_code == 200
        assert res.json().get("ok") is True
        user = db.query(User).filter(User.id == 1).first()
        assert user is not None
        assert bool(getattr(user, "is_deleted", False)) is True
        assert user.deleted_at is not None
        assert user.deletion_scheduled_for is not None
        # Data retained for restore.
        assert db.query(Profile).filter(Profile.user_id == 1).first() is not None
        assert db.query(Message).filter(Message.sender_id == 1).count() == 1
        assert db.query(Subscription).filter(Subscription.user_id == 1).count() == 1
        assert db.query(AnalyticsEvent).filter(AnalyticsEvent.name == "x").first().user_id == 1
    finally:
        db.close()

