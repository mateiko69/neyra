from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.deps import get_current_user, get_db
from app.api.v1.endpoints import ai as ai_module
from app.api.v1.endpoints.ai import router
from app.db.base import Base
from app.models.message import Message
from app.models.profile import Profile
from app.models.subscription import Subscription
from app.models.user import User
from app.services.ai.conversation_coach import assess_conversation, polish_reply_quality


def test_short_cold_replies_wait_or_reengage_low_meeting_readiness() -> None:
    out = assess_conversation(
        last_messages=[
            {"role": "me", "text": "Hey, how was your day?"},
            {"role": "partner", "text": "ok"},
            {"role": "me", "text": "Nice, doing anything fun later?"},
            {"role": "partner", "text": "no"},
        ],
        locale="en",
    )
    assert out.recommended_move in {"ask_question", "revive", "wait"}
    assert out.meeting_readiness < 45


def test_mutual_warm_replies_flirt_or_deepen() -> None:
    out = assess_conversation(
        last_messages=[
            {"role": "me", "text": "Your hiking photo is great, where was that?"},
            {"role": "partner", "text": "Haha thanks, Carpathians. I love that place 🙂"},
            {"role": "me", "text": "That sounds like my kind of weekend."},
            {"role": "partner", "text": "Same, I like easy trips and coffee after."},
            {"role": "me", "text": "Coffee after a trail is elite."},
            {"role": "partner", "text": "Exactly 😂 what trail would you pick?"},
        ],
        locale="en",
    )
    assert out.recommended_move in {"flirt", "deepen", "reply"}
    assert out.flirt_readiness >= 45


def test_high_momentum_ready_soft() -> None:
    t0 = datetime.now(UTC)
    msgs = []
    for i in range(14):
        msgs.append(
            {
                "role": "me" if i % 2 == 0 else "partner",
                "text": "Haha yes, coffee and travel sound fun. What place would you choose?",
                "created_at": t0 + timedelta(minutes=i * 4),
            }
        )
    out = assess_conversation(last_messages=msgs, conversation_stage="meeting_ready", locale="uk")
    assert out.meeting_readiness_meta in {"ready_soft", "ready_direct"}
    if out.meeting_readiness_meta == "ready_soft":
        assert out.casual_meeting_line == "З тобою було б цікаво випити каву 🙂"


def test_cringe_reply_gets_rewritten() -> None:
    out = polish_reply_quality("You are my destiny, send nudes, why aren't you replying????", locale="en")
    assert out["text"] != "You are my destiny, send nudes, why aren't you replying????"
    assert out["quality_score"] < 80
    assert {"too_poetic", "overly_sexual", "too_needy"} & set(out["quality_flags"])


def _memory_db() -> Session:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _client_for_plan(plan: str, monkeypatch) -> TestClient:
    db = _memory_db()
    u1 = User(email=f"{plan}@example.com", hashed_password="x", is_active=True)
    u2 = User(email=f"{plan}.partner@example.com", hashed_password="x", is_active=True)
    db.add_all([u1, u2])
    db.flush()
    db.add_all(
        [
            Profile(user_id=u1.id, display_name="Alex", interests="coffee, hiking", city="Kyiv"),
            Profile(user_id=u2.id, display_name="Mira", interests="coffee, hiking", city="Kyiv"),
        ]
    )
    if plan != "free":
        db.add(Subscription(user_id=u1.id, provider="mock", status="active", plan_code=plan))
    now = datetime.now(UTC)
    for i in range(8):
        db.add(
            Message(
                sender_id=u1.id if i % 2 == 0 else u2.id,
                receiver_id=u2.id if i % 2 == 0 else u1.id,
                content="Кава і прогулянки звучать класно, що тобі ближче?",
                created_at=now + timedelta(minutes=i),
            )
        )
    db.commit()

    app = FastAPI()
    app.include_router(router, prefix="/api/v1/ai")
    app.dependency_overrides[get_current_user] = lambda: u1
    app.dependency_overrides[get_db] = lambda: db
    monkeypatch.setattr(ai_module.settings, "ENABLE_AI_SUGGESTIONS", True)
    monkeypatch.setattr(ai_module, "is_blocked", lambda _db, _a, _b: False)
    monkeypatch.setattr(ai_module, "users_are_matched", lambda _db, _a, _b: True)
    app.state.partner_id = int(u2.id)
    return TestClient(app)


def test_next_move_premium_receives_coach_meta_free_does_not(monkeypatch) -> None:
    free = _client_for_plan("free", monkeypatch)
    partner_id = free.app.state.partner_id
    r = free.get(f"/api/v1/ai/coach/next-move?partner_user_id={partner_id}&locale=uk")
    assert r.status_code == 200
    assert "coach" not in r.json()

    premium = _client_for_plan("premium", monkeypatch)
    partner_id = premium.app.state.partner_id
    r2 = premium.get(f"/api/v1/ai/coach/next-move?partner_user_id={partner_id}&locale=uk")
    assert r2.status_code == 200
    payload = r2.json()
    assert "coach" in payload
    assert payload["meeting_readiness"] in {"not_ready", "warming_up", "ready_soft", "ready_direct"}
    assert payload["advice"]
    assert any(ch in payload["advice"] for ch in "іїєКПМЗД")
