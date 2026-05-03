from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.message import Message
from app.models.user import User
from app.services.learning.message_learning import run_message_learning_tick
from app.services.ai.memory import build_memory_context_for_prompt


def _memory_session() -> Session:
    engine = create_engine(
        "sqlite://",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return Session(engine)


def test_learning_tick_writes_message_outcomes_memory() -> None:
    db = _memory_session()
    try:
        db.add(User(id=1, email="a@example.com", hashed_password="x", is_active=True, is_demo=False))
        db.add(User(id=2, email="b@example.com", hashed_password="x", is_active=True, is_demo=False))
        db.commit()

        t0 = datetime.now(UTC) - timedelta(hours=2)
        # User 1 sends two messages; user 2 replies only to the first.
        db.add(Message(sender_id=1, receiver_id=2, content="hey!! 😂", created_at=t0))
        db.add(Message(sender_id=2, receiver_id=1, content="hi", created_at=t0 + timedelta(minutes=5)))
        db.add(Message(sender_id=1, receiver_id=2, content="This is a longer serious message without emojis.", created_at=t0 + timedelta(minutes=10)))
        db.commit()

        stats = run_message_learning_tick(db, lookback_days=7, max_users=10)
        assert stats.users_updated >= 1

        mem = build_memory_context_for_prompt(db, user_id=1, partner_user_id=None)
        cp = (mem.get("AI_MEMORY") or {}).get("conversation_patterns") or {}
        assert "message_outcomes" in cp
        assert (cp.get("message_outcomes") or {}).get("total") is not None
    finally:
        db.close()

