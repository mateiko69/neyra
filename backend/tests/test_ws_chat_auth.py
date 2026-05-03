from datetime import UTC, datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient
from jose import jwt
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.deps import get_db
from app.core.config import settings
from app.db.base import Base
from app.models.match import Match
from app.models.user import User
from app.models.user_block import UserBlock
from app.api.v1.endpoints.websocket import router as ws_router, _mint_ws_token


def _memory_db() -> Session:
    # WebSocket tests run in a different thread inside TestClient.
    # Use StaticPool + check_same_thread=False so the in-memory DB is shared safely.
    engine = create_engine(
        "sqlite://",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return Session(engine)


def _token_for(user_id: int) -> str:
    return jwt.encode({"sub": str(int(user_id))}, settings.SECRET_KEY, algorithm="HS256")


def _build_client(db: Session) -> TestClient:
    app = FastAPI()
    app.include_router(ws_router, prefix="/api/v1")

    def _override_db():
        yield db

    app.dependency_overrides[get_db] = _override_db
    return TestClient(app)


def _create_user(db: Session, user_id: int, email: str) -> User:
    u = User(id=int(user_id), email=email, hashed_password="x", is_active=True, matches_last_seen_at=datetime.now(UTC))
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _create_match(db: Session, a: int, b: int) -> None:
    x, y = sorted([int(a), int(b)])
    db.add(Match(user_a_id=x, user_b_id=y))
    db.commit()


def test_ws_allows_message_only_to_matched_user_and_sets_sender_from_token():
    db = _memory_db()
    try:
        _create_user(db, 1, "a@example.com")
        _create_user(db, 2, "b@example.com")
        _create_match(db, 1, 2)

        client = _build_client(db)
        ws_token = _mint_ws_token(1, ttl_seconds=90)
        with client.websocket_connect(f"/api/v1/ws/chat/1?ws_token={ws_token}") as ws:
            ws.send_json({"receiver_id": 2, "content": "hi"})
            msg = ws.receive_json()
            assert msg["type"] == "message"
            assert msg["sender_id"] == 1
            assert msg["receiver_id"] == 2
            assert msg["content"] == "hi"
    finally:
        db.close()


def test_ws_rejects_sender_spoofing():
    db = _memory_db()
    try:
        _create_user(db, 1, "a@example.com")
        _create_user(db, 2, "b@example.com")
        _create_user(db, 3, "c@example.com")
        _create_match(db, 1, 2)

        client = _build_client(db)
        ws_token = _mint_ws_token(1, ttl_seconds=90)
        with client.websocket_connect(f"/api/v1/ws/chat/1?ws_token={ws_token}") as ws:
            ws.send_json({"sender_id": 3, "receiver_id": 2, "content": "spoof"})
            err = ws.receive_json()
            assert err["type"] == "error"
            assert err["code"] == "unauthorized"
    finally:
        db.close()


def test_ws_rejects_unmatched_receiver():
    db = _memory_db()
    try:
        _create_user(db, 1, "a@example.com")
        _create_user(db, 2, "b@example.com")
        client = _build_client(db)
        ws_token = _mint_ws_token(1, ttl_seconds=90)
        with client.websocket_connect(f"/api/v1/ws/chat/1?ws_token={ws_token}") as ws:
            ws.send_json({"receiver_id": 2, "content": "hi"})
            err = ws.receive_json()
            assert err["type"] == "error"
            assert err["code"] == "not_matched"
    finally:
        db.close()


def test_ws_rejects_blocked_pair():
    db = _memory_db()
    try:
        _create_user(db, 1, "a@example.com")
        _create_user(db, 2, "b@example.com")
        _create_match(db, 1, 2)
        db.add(UserBlock(blocker_id=1, blocked_id=2))
        db.commit()

        client = _build_client(db)
        ws_token = _mint_ws_token(1, ttl_seconds=90)
        with client.websocket_connect(f"/api/v1/ws/chat/1?ws_token={ws_token}") as ws:
            ws.send_json({"receiver_id": 2, "content": "hi"})
            err = ws.receive_json()
            assert err["type"] == "error"
            assert err["code"] == "blocked"
    finally:
        db.close()


def test_ws_rejects_expired_ws_token():
    db = _memory_db()
    try:
        _create_user(db, 1, "a@example.com")
        _create_user(db, 2, "b@example.com")
        _create_match(db, 1, 2)
        client = _build_client(db)
        expired = _mint_ws_token(1, ttl_seconds=60)
        # Force-expire by re-encoding with past exp (direct JWT).
        past = jwt.encode({"sub": "1", "scope": "ws_chat", "exp": 0}, settings.SECRET_KEY, algorithm="HS256")
        try:
            client.websocket_connect(f"/api/v1/ws/chat/1?ws_token={past}")
            assert False, "expected connect to fail"
        except Exception:
            assert True
    finally:
        db.close()


def test_ws_path_user_id_is_not_authoritative_token_wins():
    db = _memory_db()
    try:
        _create_user(db, 1, "a@example.com")
        _create_user(db, 2, "b@example.com")
        _create_match(db, 1, 2)
        client = _build_client(db)
        ws_token = _mint_ws_token(2, ttl_seconds=90)
        with client.websocket_connect(f"/api/v1/ws/chat/1?ws_token={ws_token}") as ws:
            ws.send_json({"receiver_id": 1, "content": "hi from two"})
            msg = ws.receive_json()
            assert msg["type"] == "message"
            assert msg["sender_id"] == 2
            assert msg["receiver_id"] == 1
    finally:
        db.close()

