from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.deps import get_current_user, get_db
from app.api.v1.endpoints.messages import router as messages_router
from app.api.v1.endpoints.swipes import router as swipes_router
from app.db.base import Base
from app.models.match import Match
from app.models.message import Message
from app.models.profile import Profile
from app.models.swipe import Swipe
from app.models.user import User
from app.services.demo_behavior import run_demo_behavior_tick
from app.services.demo_message_templates import get_demo_first_match_message


def _memory_db() -> Session:
    engine = create_engine(
        "sqlite://",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return Session(engine)


def _client(db: Session, current_user: User) -> TestClient:
    app = FastAPI()
    app.include_router(swipes_router, prefix="/api/v1/swipes")
    app.include_router(messages_router, prefix="/api/v1/messages")

    def _override_db():
        yield db

    def _override_user():
        return current_user

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_user] = _override_user
    return TestClient(app)


def _seed_real_and_demo(db: Session) -> tuple[User, User]:
    real = User(email="real@example.com", hashed_password="x", is_active=True, is_demo=False)
    demo = User(email="demo+maya@neyra.local", hashed_password=None, is_active=True, is_demo=True)
    db.add_all([real, demo])
    db.flush()
    db.add(
        Profile(
            user_id=int(real.id),
            display_name="Real",
            preferred_language="uk",
            photo_urls="r.jpg",
            onboarding_completed=True,
            is_demo_profile=False,
        )
    )
    db.add(
        Profile(
            user_id=int(demo.id),
            display_name="Maya Demo",
            is_demo_profile=True,
            photo_urls="d.jpg",
            demo_personality_json='{"personality":"curious","response_speed":"fast","engagement_level":0.9}',
        )
    )
    db.commit()
    return real, demo


def test_like_demo_profile_auto_creates_reciprocal_like_and_match() -> None:
    db = _memory_db()
    try:
        real, demo = _seed_real_and_demo(db)
        c = _client(db, real)
        r = c.post("/api/v1/swipes", json={"target_user_id": int(demo.id), "liked": True})
        assert r.status_code == 200
        body = r.json()
        assert body.get("matched") is True
        assert body.get("is_demo_match") is True
        assert str(body.get("chat_url") or "").startswith(f"/chat/{int(demo.id)}")

        recip = db.query(Swipe).filter(Swipe.swiper_id == int(demo.id), Swipe.target_user_id == int(real.id)).first()
        assert recip is not None
        assert bool(recip.liked) is True

        a, b = sorted([int(real.id), int(demo.id)])
        assert db.query(Match).filter(Match.user_a_id == a, Match.user_b_id == b).count() == 1
    finally:
        db.close()


def test_repeated_like_demo_profile_is_idempotent_no_duplicate_match_or_first_message() -> None:
    db = _memory_db()
    try:
        real, demo = _seed_real_and_demo(db)
        c = _client(db, real)
        c.post("/api/v1/swipes", json={"target_user_id": int(demo.id), "liked": True})
        run_demo_behavior_tick(db)
        c.post("/api/v1/swipes", json={"target_user_id": int(demo.id), "liked": True})
        run_demo_behavior_tick(db)

        a, b = sorted([int(real.id), int(demo.id)])
        assert db.query(Match).filter(Match.user_a_id == a, Match.user_b_id == b).count() == 1
        first_msgs = (
            db.query(Message)
            .filter(Message.sender_id == int(demo.id), Message.receiver_id == int(real.id))
            .all()
        )
        assert len(first_msgs) <= 1
    finally:
        db.close()


def test_demo_first_opener_uses_locale_context_not_generic(monkeypatch) -> None:
    db = _memory_db()
    try:
        real, demo = _seed_real_and_demo(db)
        c = _client(db, real)
        r = c.post("/api/v1/swipes", json={"target_user_id": int(demo.id), "liked": True})
        assert r.status_code == 200
        # Force generic AI opener -> demo layer should contextualize.
        monkeypatch.setattr(
            "app.services.ai.orchestrator.AIOrchestrator.generate_demo_opener",
            staticmethod(lambda **_: "Hello, how are you?"),
        )
        prof = db.query(Profile).filter(Profile.user_id == int(demo.id)).first()
        assert prof is not None
        assert prof.demo_reply_scheduled_at is not None
        prof.demo_reply_scheduled_at = __import__("datetime").datetime.now(__import__("datetime").UTC) - __import__("datetime").timedelta(seconds=1)
        db.add(prof)
        db.commit()
        run_demo_behavior_tick(db)
        out = (
            db.query(Message)
            .filter(Message.sender_id == int(demo.id), Message.receiver_id == int(real.id))
            .order_by(Message.created_at.desc())
            .first()
        )
        assert out is not None
        txt = str(out.content or "").strip().lower()
        assert "hello, how are you" not in txt
        assert "?" in txt
    finally:
        db.close()


def test_non_demo_like_does_not_auto_match() -> None:
    db = _memory_db()
    try:
        a = User(email="a@example.com", hashed_password="x", is_active=True, is_demo=False)
        b = User(email="b@example.com", hashed_password="x", is_active=True, is_demo=False)
        db.add_all([a, b])
        db.flush()
        db.add(Profile(user_id=int(a.id), display_name="A", photo_urls="a.jpg"))
        db.add(Profile(user_id=int(b.id), display_name="B", photo_urls="b.jpg"))
        db.commit()
        c = _client(db, a)
        r = c.post("/api/v1/swipes", json={"target_user_id": int(b.id), "liked": True})
        assert r.status_code == 200
        assert r.json().get("matched") is False
    finally:
        db.close()


def test_demo_first_message_localized_examples() -> None:
    assert "demo profile" in get_demo_first_match_message("en").lower()
    assert "демо-проф" in get_demo_first_match_message("uk").lower()
    assert "демо-проф" in get_demo_first_match_message("ru").lower()
    assert "perfil de demo" in get_demo_first_match_message("es").lower()
    assert "演示" in get_demo_first_match_message("zh")


def test_get_thread_returns_user_and_demo_messages() -> None:
    db = _memory_db()
    try:
        real, demo = _seed_real_and_demo(db)
        a, b = sorted([int(real.id), int(demo.id)])
        db.add(Match(user_a_id=a, user_b_id=b))
        db.flush()
        db.add(Message(sender_id=int(real.id), receiver_id=int(demo.id), content="Hi demo"))
        db.add(Message(sender_id=int(demo.id), receiver_id=int(real.id), content="Hey! I am a demo profile."))
        db.commit()

        c = _client(db, real)
        r = c.get(f"/api/v1/messages/{int(demo.id)}")
        assert r.status_code == 200
        body = r.json()
        msgs = body.get("messages") or []
        assert len(msgs) == 2
        assert {int(m.get("sender_id")) for m in msgs} == {int(real.id), int(demo.id)}
        for msg in msgs:
            assert "id" in msg
            assert "sender_id" in msg
            assert "receiver_id" in msg
            assert "content" in msg
            assert "created_at" in msg
            assert "is_read" in msg
    finally:
        db.close()
