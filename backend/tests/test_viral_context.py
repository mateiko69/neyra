from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.message import Message
from app.models.profile import Profile
from app.models.user import User
from app.services.viral.viral_context import get_viral_context, signups_today_count


def _session() -> Session:
    engine = create_engine("sqlite://", future=True, connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return Session(engine)


def test_signups_today_counts_non_demo_users() -> None:
    db = _session()
    try:
        now = datetime.now(UTC)
        db.add(
            User(
                email="a@example.com",
                hashed_password="x",
                is_active=True,
                is_demo=False,
                created_at=now - timedelta(hours=1),
            )
        )
        db.commit()
        assert signups_today_count(db) >= 1
    finally:
        db.close()


def test_viral_context_includes_visibility_tier() -> None:
    db = _session()
    try:
        now = datetime.now(UTC)
        u1 = User(email="u@example.com", hashed_password="x", is_active=True, is_demo=False, last_active_at=now)
        u2 = User(email="p@example.com", hashed_password="x", is_active=True, is_demo=False)
        db.add(u1)
        db.add(u2)
        db.flush()
        db.add(Profile(user_id=u1.id, display_name="Me", bio="x" * 40, interests="a,b,c", photo_urls="http://x/a.jpg"))
        db.add(Profile(user_id=u2.id, display_name="Pal"))
        db.commit()
        for i in range(6):
            db.add(Message(sender_id=u1.id, receiver_id=u2.id, content=f"m{i}", created_at=now - timedelta(hours=i)))
        db.commit()
        ctx = get_viral_context(db, u1.id)
        assert ctx["visibility_loop"]["tier"] in {"high", "medium", "low"}
        assert "social_proof" in ctx
    finally:
        db.close()
