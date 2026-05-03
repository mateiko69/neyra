"""Dedupe ``ai_fallback_triggered`` per HTTP request (logical endpoint + provider; one primary log)."""

from __future__ import annotations

import asyncio
import logging

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.deps import get_current_user, get_db
from app.api.v1.endpoints import ai as ai_module
from app.api.v1.endpoints.ai import router as ai_router
from app.db.base import Base
from app.models.profile import Profile
from app.models.user import User
from app.services.ai.ai_generation_context import reset_ai_generation_log_context
from app.services.ai.gemini_client import GeminiError
from app.services.ai.safe_ai import log_ai_fallback_triggered, safe_ai_generate_async


def _count_fallback_trigger_logs(caplog: pytest.LogCaptureFixture) -> int:
    return sum(1 for r in caplog.records if "ai_fallback_triggered" in r.getMessage())


def test_log_ai_fallback_triggered_dedupes_same_request(caplog: pytest.LogCaptureFixture) -> None:
    reset_ai_generation_log_context()
    caplog.set_level(logging.WARNING, logger="neyra.ai.safe")
    assert log_ai_fallback_triggered(
        endpoint="timed-replies",
        locale="en",
        reason="quota_exhausted",
        error_message="x",
        provider="gemini",
    )
    assert not log_ai_fallback_triggered(
        endpoint="timed-replies",
        locale="en",
        reason="quota_exhausted",
        error_message="different body",
        provider="gemini",
    )
    assert _count_fallback_trigger_logs(caplog) == 1
    assert sum(1 for r in caplog.records if "gemini_suppressed_same_request" in r.getMessage()) == 1


def test_different_reason_same_endpoint_only_primary_fallback_log(caplog: pytest.LogCaptureFixture) -> None:
    """Second failure same endpoint → suppressed log only (not a second ``ai_fallback_triggered``)."""
    reset_ai_generation_log_context()
    caplog.set_level(logging.WARNING, logger="neyra.ai.safe")
    assert log_ai_fallback_triggered(
        endpoint="timed-replies", locale="en", reason="a", error_message="x", provider="gemini"
    )
    assert not log_ai_fallback_triggered(
        endpoint="timed-replies", locale="en", reason="b", error_message="x", provider="gemini"
    )
    assert _count_fallback_trigger_logs(caplog) == 1
    assert sum(1 for r in caplog.records if "gemini_suppressed_same_request" in r.getMessage()) == 1


def test_chat_brain_sub_endpoints_share_dedupe_bucket(caplog: pytest.LogCaptureFixture) -> None:
    """tone_pack + one_line map to logical ``chat-brain/suggestions`` for dedupe."""
    reset_ai_generation_log_context()
    caplog.set_level(logging.WARNING, logger="neyra.ai.safe")

    async def _run() -> None:
        async def _fail() -> int:
            raise GeminiError(code="global_failure_cooldown", message="cooldown")

        async def _fb() -> int:
            return 42

        await safe_ai_generate_async(_fail, _fb, endpoint="chat-brain/tone_pack", locale="en")
        await safe_ai_generate_async(_fail, _fb, endpoint="chat-brain/one_line", locale="en")

    asyncio.run(_run())
    assert _count_fallback_trigger_logs(caplog) == 1


def _memory_session():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from sqlalchemy.pool import StaticPool

    engine = create_engine(
        "sqlite://",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return Session(engine)


def test_timed_replies_gemini_failure_logs_fallback_once_and_returns_three_options(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Single ``ai_fallback_triggered`` for one POST despite internal fallback row work."""
    reset_ai_generation_log_context()
    caplog.set_level(logging.WARNING, logger="neyra.ai.safe")

    from app.core import config as config_mod

    monkeypatch.setattr(config_mod.settings, "ENABLE_AI_SUGGESTIONS", True, raising=False)
    monkeypatch.setattr(config_mod.settings, "AI_PROVIDER", "gemini", raising=False)
    monkeypatch.setattr(config_mod.settings, "GEMINI_API_KEY", "fake-key-for-test", raising=False)

    db = _memory_session()
    try:
        u = User(email="trfb@example.com", hashed_password="x", is_active=True)
        db.add(u)
        db.flush()
        db.add(Profile(user_id=int(u.id), display_name="Me", photo_urls="m.jpg", city="Kyiv", bio="hi"))
        db.commit()

        app = FastAPI()
        app.include_router(ai_router, prefix="/api/v1/ai")

        def _db():
            yield db

        app.dependency_overrides[get_db] = _db
        app.dependency_overrides[get_current_user] = lambda: u

        monkeypatch.setattr(
            ai_module,
            "enforce_and_consume_ai_usage",
            lambda db, user_id, usage_type="message": ("premium", None),
        )
        monkeypatch.setattr(ai_module, "enforce_ai_limits", lambda _db, _uid: None)

        class _GC:
            async def generate_json(self, **kwargs):
                raise GeminiError(code="quota_exhausted", message="upstream")

        monkeypatch.setattr(ai_module, "GeminiClient", lambda: _GC())

        c = TestClient(app)
        r = c.post(
            "/api/v1/ai/timed-replies",
            json={
                "messages": [{"role": "them", "text": "Hey what's up?"}],
                "nudge_type": "now",
                "interest_stage": "warming",
                "mutuality_score": 40,
                "locale": "en",
            },
        )
        assert r.status_code == 200
        body = r.json()
        opts = body.get("options") or []
        assert len(opts) == 3
        assert _count_fallback_trigger_logs(caplog) == 1
    finally:
        db.close()
