"""AI reliability: user-facing endpoints return 200 with fallbacks when Gemini fails."""

from __future__ import annotations

import asyncio

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.deps import get_current_user, get_db
from app.api.v1.endpoints import ai as ai_endpoints
from app.core.config import settings
from app.db.base import Base
from app.models.match import Match
from app.models.message import Message
from app.models.profile import Profile
from app.models.user import User
from app.services.ai.gemini_client import GeminiClient, GeminiError


def _memory_db() -> Session:
    engine = create_engine(
        "sqlite://",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return Session(engine)


def _app_with_user(me: User, db: Session) -> TestClient:
    app = FastAPI()
    app.include_router(ai_endpoints.router, prefix="/api/v1/ai")

    def _override_db():
        yield db

    def _override_user():
        return me

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_user] = _override_user
    return TestClient(app)


async def _boom(*_a, **_k):
    raise GeminiError("server_error", "forced failure", 500)


def test_meeting_options_gemini_failure_returns_fallback(monkeypatch):
    monkeypatch.setattr(settings, "AI_PROVIDER", "gemini")
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "x")
    monkeypatch.setattr(settings, "ENABLE_AI_SUGGESTIONS", True)
    monkeypatch.setattr(GeminiClient, "generate_json", _boom)

    db = _memory_db()
    try:
        me = User(email="mopt@x.com", hashed_password="x", is_active=True)
        db.add(me)
        db.commit()
        client = _app_with_user(me, db)
        r = client.post(
            "/api/v1/ai/meeting-options",
            json={"meeting_readiness": 85, "messages": ["Hi there"], "locale": "en"},
        )
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data.get("meeting_options"), list)
        assert len(data["meeting_options"]) >= 1
    finally:
        db.close()


def test_interest_stage_gemini_failure_returns_fallback(monkeypatch):
    monkeypatch.setattr(settings, "AI_PROVIDER", "gemini")
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "x")
    monkeypatch.setattr(settings, "ENABLE_AI_SUGGESTIONS", True)
    monkeypatch.setattr(GeminiClient, "generate_json", _boom)

    db = _memory_db()
    try:
        me = User(email="ist@x.com", hashed_password="x", is_active=True)
        db.add(me)
        db.commit()
        client = _app_with_user(me, db)
        r = client.post("/api/v1/ai/interest-stage", json={"messages": ["Hey"]})
        assert r.status_code == 200
        body = r.json()
        assert "interest_score" in body and "stage" in body
    finally:
        db.close()


def test_timing_engine_gemini_failure_returns_fallback(monkeypatch):
    monkeypatch.setattr(settings, "AI_PROVIDER", "gemini")
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "x")
    monkeypatch.setattr(settings, "ENABLE_AI_SUGGESTIONS", True)
    monkeypatch.setattr(GeminiClient, "generate_json", _boom)

    db = _memory_db()
    try:
        me = User(email="te@x.com", hashed_password="x", is_active=True)
        db.add(me)
        db.commit()
        client = _app_with_user(me, db)
        r = client.post(
            "/api/v1/ai/timing-engine",
            json={
                "messages": [],
                "locale": "en",
                "last_message_at": None,
                "avg_partner_reply_minutes": None,
                "partner_active_hours": [],
                "stall_score": 10,
                "interest_stage": "warming",
                "mutuality_score": 50,
            },
        )
        assert r.status_code == 200
        assert "nudge_type" in r.json()
    finally:
        db.close()


def test_suggest_next_step_wrap_returns_escalation_fallback(monkeypatch):
    from app.application.use_cases.ai import wingman_next_step as ns_mod

    class _P:
        async def suggest_next_step(self, _analysis):
            raise GeminiError("x", "fail", 500)

    monkeypatch.setattr(ns_mod, "get_ai_provider", lambda: _P())

    payload = {"interest_level": 40, "response_quality": 40, "risk_of_drop": 30, "energy_level": "mid", "flags": []}
    out = asyncio.run(ns_mod.suggest_next_step(payload))
    assert isinstance(out, dict)


def test_recovery_endpoint_ok_without_gemini():
    db = _memory_db()
    try:
        me = User(email="recv@x.com", hashed_password="x", is_active=True)
        db.add(me)
        db.commit()
        client = _app_with_user(me, db)
        r = client.post(
            "/api/v1/ai/recovery",
            json={
                "messages": [{"role": "them", "text": "Hi"}],
                "last_message_age_minutes": 60,
                "readiness_score": 40,
                "coach_state": None,
                "locale": "en",
            },
        )
        assert r.status_code == 200
        j = r.json()
        assert "message" in j and "suggestions" in j
        assert isinstance(j["suggestions"], list)
    finally:
        db.close()
