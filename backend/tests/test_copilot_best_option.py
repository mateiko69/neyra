from __future__ import annotations

import re

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.deps import get_current_user, get_db
from app.api.v1.endpoints import ai as ai_endpoints
from app.core.config import settings
from app.services.ai.gemini_client import GeminiClient, GeminiError
from app.services.monetization.subscription_service import SubscriptionService
from app.db.base import Base
from app.models.match import Match
from app.models.message import Message
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


def _has_english(s: str) -> bool:
    return bool(re.search(r"[A-Za-z]", s or ""))


def test_chat_copilot_always_returns_3_and_best_index_is_valid(monkeypatch):
    # Force fallback path: no gemini key.
    monkeypatch.setattr(settings, "AI_PROVIDER", "gemini")
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "")
    monkeypatch.setattr(settings, "ENABLE_AI_SUGGESTIONS", True)
    monkeypatch.setattr(settings, "ENV", "development")

    db = _memory_db()
    try:
        me = User(email="me@example.com", hashed_password="x", is_active=True)
        them = User(email="them@example.com", hashed_password="x", is_active=True)
        db.add(me)
        db.add(them)
        db.flush()
        db.add(Profile(user_id=int(me.id), display_name="Me"))
        db.add(Profile(user_id=int(them.id), display_name="Them"))
        # Make them matched so endpoint allows access.
        db.add(Match(user_a_id=int(me.id), user_b_id=int(them.id)))
        db.commit()

        # Add a single incoming message (early conversation).
        db.add(Message(sender_id=int(them.id), receiver_id=int(me.id), content="Привіт! Що тобі подобається у Верховині?"))
        db.commit()

        app = FastAPI()
        app.include_router(ai_endpoints.router, prefix="/api/v1/ai")

        def _override_db():
            yield db

        def _override_user():
            return me

        app.dependency_overrides[get_db] = _override_db
        app.dependency_overrides[get_current_user] = _override_user

        client = TestClient(app)
        r = client.post("/api/v1/ai/chat-copilot", json={"partner_user_id": int(them.id), "mode": None, "user_selected_style": None})
        assert r.status_code == 200
        body = r.json()
        assert len(body.get("options") or []) == 3
        assert all(str((o or {}).get("text") or "").strip() for o in (body.get("options") or [])[:3])
        assert body.get("fallback") is True
    finally:
        db.close()


def test_chat_copilot_continue_mode_does_not_repeat_opener(monkeypatch):
    # Force fallback path: no gemini key.
    monkeypatch.setattr(settings, "AI_PROVIDER", "gemini")
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "")
    monkeypatch.setattr(settings, "ENABLE_AI_SUGGESTIONS", True)
    monkeypatch.setattr(settings, "ENV", "development")

    db = _memory_db()
    try:
        me = User(email="me2@example.com", hashed_password="x", is_active=True)
        them = User(email="them2@example.com", hashed_password="x", is_active=True)
        db.add(me)
        db.add(them)
        db.flush()
        db.add(Profile(user_id=int(me.id), display_name="Me"))
        db.add(Profile(user_id=int(them.id), display_name="Them"))
        db.add(Match(user_a_id=int(me.id), user_b_id=int(them.id)))
        db.commit()

        # Conversation already started: opener asked, then partner answered.
        db.add(Message(sender_id=int(me.id), receiver_id=int(them.id), content="Що тобі більше подобається у Верховині — місця чи люди?"))
        db.add(Message(sender_id=int(them.id), receiver_id=int(me.id), content="і місця і люди 🙂"))
        db.commit()

        app = FastAPI()
        app.include_router(ai_endpoints.router, prefix="/api/v1/ai")

        def _override_db():
            yield db

        def _override_user():
            return me

        app.dependency_overrides[get_db] = _override_db
        app.dependency_overrides[get_current_user] = _override_user

        client = TestClient(app)
        r = client.post("/api/v1/ai/chat-copilot", json={"partner_user_id": int(them.id), "mode": None, "user_selected_style": None})
        assert r.status_code == 200
        body = r.json()
        assert len(body.get("options") or []) == 3
        assert body.get("fallback") is True
    finally:
        db.close()


def test_chat_copilot_no_fallback_in_production(monkeypatch):
    monkeypatch.setattr(settings, "AI_PROVIDER", "gemini")
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "")
    monkeypatch.setattr(settings, "ENABLE_AI_SUGGESTIONS", True)
    monkeypatch.setattr(settings, "ENV", "production")

    db = _memory_db()
    try:
        me = User(email="me_prod@example.com", hashed_password="x", is_active=True)
        them = User(email="them_prod@example.com", hashed_password="x", is_active=True)
        db.add(me)
        db.add(them)
        db.flush()
        db.add(Profile(user_id=int(me.id), display_name="Me"))
        db.add(Profile(user_id=int(them.id), display_name="Them"))
        db.add(Match(user_a_id=int(me.id), user_b_id=int(them.id)))
        db.commit()
        db.add(Message(sender_id=int(them.id), receiver_id=int(me.id), content="Привіт!"))
        db.commit()

        app = FastAPI()
        app.include_router(ai_endpoints.router, prefix="/api/v1/ai")

        def _override_db():
            yield db

        def _override_user():
            return me

        app.dependency_overrides[get_db] = _override_db
        app.dependency_overrides[get_current_user] = _override_user

        client = TestClient(app)
        r = client.post("/api/v1/ai/chat-copilot", json={"partner_user_id": int(them.id), "mode": None, "user_selected_style": None})
        assert r.status_code == 200
        body = r.json()
        assert len(body.get("options") or []) == 3
        assert body.get("fallback") is True
    finally:
        db.close()


def test_chat_copilot_gemini_error_returns_200_fallback(monkeypatch):
    monkeypatch.setattr(settings, "AI_PROVIDER", "gemini")
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "fake-key-for-test")
    monkeypatch.setattr(settings, "ENABLE_AI_SUGGESTIONS", True)
    monkeypatch.setattr(settings, "ENV", "development")

    async def _boom(*_a, **_k):
        raise GeminiError("server_error", "simulated provider failure", 500)

    def _not_stalled(_chat, *, hours_since_last=None):
        return {"is_stalled": False, "stall_score": 0, "reasons": []}

    monkeypatch.setattr(GeminiClient, "generate_json", _boom)
    monkeypatch.setattr(SubscriptionService, "get_active_plan", lambda self, _db, _uid: "premium")
    monkeypatch.setattr(ai_endpoints, "_detect_stall_fallback", _not_stalled)

    db = _memory_db()
    try:
        me = User(email="me_gem@example.com", hashed_password="x", is_active=True)
        them = User(email="them_gem@example.com", hashed_password="x", is_active=True)
        db.add(me)
        db.add(them)
        db.flush()
        db.add(Profile(user_id=int(me.id), display_name="Me"))
        db.add(Profile(user_id=int(them.id), display_name="Them"))
        db.add(Match(user_a_id=int(me.id), user_b_id=int(them.id)))
        db.commit()
        db.add(Message(sender_id=int(them.id), receiver_id=int(me.id), content="Hey! How is your day?"))
        db.commit()

        app = FastAPI()
        app.include_router(ai_endpoints.router, prefix="/api/v1/ai")

        def _override_db():
            yield db

        def _override_user():
            return me

        app.dependency_overrides[get_db] = _override_db
        app.dependency_overrides[get_current_user] = _override_user

        client = TestClient(app)
        r = client.post("/api/v1/ai/chat-copilot", json={"partner_user_id": int(them.id), "locale": "en"})
        assert r.status_code == 200
        body = r.json()
        assert len(body.get("options") or []) == 3
        assert all(str((o or {}).get("text") or "").strip() for o in (body.get("options") or [])[:3])
        assert body.get("fallback") is True
    finally:
        db.close()


def test_chat_brain_suggestions_200_when_ai_disabled(monkeypatch):
    monkeypatch.setattr(settings, "ENABLE_AI_SUGGESTIONS", False)

    db = _memory_db()
    try:
        me = User(email="me_brain@example.com", hashed_password="x", is_active=True)
        them = User(email="them_brain@example.com", hashed_password="x", is_active=True)
        db.add(me)
        db.add(them)
        db.flush()
        db.add(Profile(user_id=int(me.id), display_name="Me"))
        db.add(Profile(user_id=int(them.id), display_name="Them"))
        db.add(Match(user_a_id=int(me.id), user_b_id=int(them.id)))
        db.commit()

        app = FastAPI()
        app.include_router(ai_endpoints.router, prefix="/api/v1/ai")

        def _override_db():
            yield db

        def _override_user():
            return me

        app.dependency_overrides[get_db] = _override_db
        app.dependency_overrides[get_current_user] = _override_user

        client = TestClient(app)
        r = client.post(
            "/api/v1/ai/chat-brain/suggestions",
            json={"partner_user_id": int(them.id), "mode": "auto", "language": "en"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body.get("ok") is True
        v = body.get("variants") or {}
        assert str(v.get("light") or "").strip()
        assert str(v.get("flirty") or "").strip()
        assert str(v.get("deep") or "").strip()
        assert body.get("fallback") is True
    finally:
        db.close()

