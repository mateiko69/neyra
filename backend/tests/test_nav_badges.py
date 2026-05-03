from datetime import UTC, datetime, timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.deps import get_current_user, get_db
from app.api.v1.endpoints.nav import router as nav_router
from app.db.base import Base
from app.models.match import Match
from app.models.message import Message
from app.models.thread_read_state import ThreadReadState
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


class DummyUser:
    def __init__(self, user_id: int, email: str = "u@example.com"):
        self.id = int(user_id)
        self.email = email


def _build_client(db: Session, current_user_id: int) -> TestClient:
    app = FastAPI()
    app.include_router(nav_router, prefix="/api/v1/nav")

    def _override_db():
        yield db

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_user] = lambda: DummyUser(current_user_id)
    return TestClient(app)


def _create_user(db: Session, user_id: int) -> None:
    db.add(
        User(
            id=int(user_id),
            email=f"user{user_id}@example.com",
            hashed_password="x",
            is_active=True,
            matches_last_seen_at=datetime.now(UTC),
        )
    )
    db.commit()


def _match(db: Session, a: int, b: int, created_at: datetime | None = None) -> None:
    x, y = sorted([int(a), int(b)])
    row = Match(user_a_id=x, user_b_id=y)
    if created_at is not None:
        row.created_at = created_at
    db.add(row)
    db.commit()


def _send(db: Session, sender: int, receiver: int, content: str = "hi", created_at: datetime | None = None) -> None:
    m = Message(sender_id=int(sender), receiver_id=int(receiver), content=content)
    if created_at is not None:
        m.created_at = created_at
    db.add(m)
    db.commit()


def _touch_read(db: Session, user_id: int, partner_id: int, at: datetime) -> None:
    row = (
        db.query(ThreadReadState)
        .filter(ThreadReadState.user_id == int(user_id), ThreadReadState.partner_user_id == int(partner_id))
        .first()
    )
    if row:
        row.last_read_at = at
    else:
        db.add(ThreadReadState(user_id=int(user_id), partner_user_id=int(partner_id), last_read_at=at))
    db.commit()


def test_nav_badges_no_unread_initially():
    db = _memory_db()
    try:
        _create_user(db, 1)
        _create_user(db, 2)
        _match(db, 1, 2)
        client = _build_client(db, 1)
        res = client.get("/api/v1/nav/badges")
        assert res.status_code == 200
        payload = res.json()
        assert payload["unread_messages"] == 0
        assert payload["chat_threads_unread"] == 0
    finally:
        db.close()


def test_nav_badges_counts_unread_and_clears_after_read_state():
    db = _memory_db()
    try:
        _create_user(db, 1)
        _create_user(db, 2)
        _match(db, 1, 2)

        t0 = datetime.now(UTC)
        _send(db, sender=2, receiver=1, content="hey", created_at=t0)

        client = _build_client(db, 1)
        res = client.get("/api/v1/nav/badges")
        payload = res.json()
        assert payload["unread_messages"] == 1
        assert payload["chat_threads_unread"] == 1

        # User opens thread -> last_read_at >= message time means unread clears.
        _touch_read(db, user_id=1, partner_id=2, at=t0 + timedelta(seconds=1))
        res2 = client.get("/api/v1/nav/badges")
        payload2 = res2.json()
        assert payload2["unread_messages"] == 0
        assert payload2["chat_threads_unread"] == 0
    finally:
        db.close()


def test_nav_badges_distinct_threads_multiple_partners():
    db = _memory_db()
    try:
        _create_user(db, 1)
        _create_user(db, 2)
        _create_user(db, 3)
        _match(db, 1, 2)
        _match(db, 1, 3)

        _send(db, sender=2, receiver=1, content="a")
        _send(db, sender=2, receiver=1, content="b")
        _send(db, sender=3, receiver=1, content="c")

        client = _build_client(db, 1)
        res = client.get("/api/v1/nav/badges")
        payload = res.json()
        assert payload["unread_messages"] == 3
        assert payload["chat_threads_unread"] == 2
    finally:
        db.close()


def test_nav_badges_counts_demo_incoming_message_unread():
    db = _memory_db()
    try:
        _create_user(db, 1)
        _create_user(db, 2)
        # user 2 acts as demo sender for badge math; nav logic counts by sender/receiver + read state.
        _match(db, 1, 2)
        _send(db, sender=2, receiver=1, content="demo says hi")
        client = _build_client(db, 1)
        res = client.get("/api/v1/nav/badges")
        payload = res.json()
        assert payload["unread_messages"] == 1
        assert payload["chat_threads_unread"] == 1
    finally:
        db.close()

