from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.match import Match
from app.models.message import Message
from app.models.profile import Profile
from app.models.user import User
from app.services.demo_mode import demo_user_ids, purge_all_demo_users


def _session() -> Session:
    engine = create_engine(
        "sqlite://",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return Session(engine)


def test_purge_all_demo_users_removes_demo_and_messages() -> None:
    db = _session()
    try:
        db.add(User(id=1, email="real@example.com", hashed_password="x", is_active=True, is_demo=False))
        db.add(User(id=2, email="demo+demo_x@neyra.local", hashed_password=None, is_active=True, is_demo=True))
        db.add(Profile(user_id=2, display_name="D", bio="", is_demo_profile=True))
        db.add(Match(user_a_id=1, user_b_id=2))
        db.add(Message(sender_id=1, receiver_id=2, content="hi"))
        db.commit()

        assert demo_user_ids(db) == [2]
        out = purge_all_demo_users(db)
        assert out["ok"] is True
        assert int(out.get("users_deleted") or 0) >= 1
        assert db.query(User).filter(User.id == 1).count() == 1
        assert db.query(User).filter(User.is_demo == True).count() == 0  # noqa: E712
        assert db.query(Message).count() == 0
        assert db.query(Match).count() == 0
        assert db.query(Profile).filter(Profile.user_id == 2).count() == 0
    finally:
        db.close()
