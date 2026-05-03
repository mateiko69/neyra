from __future__ import annotations

import asyncio
import json
import logging

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.deps import get_current_user, get_db
from app.api.v1.endpoints import ai as ai_endpoints
from app.core.config import settings
from app.db.base import Base
from app.models.profile import Profile
from app.models.user import User
from app.services.ai.gemini_client import GeminiClient, GeminiError
from app.services.ai.rate_limit import RateLimitExceeded
from pydantic import BaseModel


def _memory_db() -> Session:
    engine = create_engine(
        "sqlite://",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return Session(engine)


def test_gemini_missing_key_logs_error(caplog, monkeypatch):
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "")
    monkeypatch.setattr(settings, "GEMINI_MODEL", "gemini-3.0-flash")
    caplog.set_level(logging.ERROR)

    client = GeminiClient()
    with pytest.raises(GeminiError):
        asyncio.run(client.generate_json(system_prompt="{}", user_prompt="{}", out_model=None, max_retries=0))

    assert any((r.getMessage() == "gemini_error") or (getattr(r, "event", None) == "gemini_error") for r in caplog.records)


def test_gemini_invalid_model_logs_error(caplog, monkeypatch):
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "not-a-real-key")
    monkeypatch.setattr(settings, "GEMINI_MODEL", "bad model with spaces")
    caplog.set_level(logging.ERROR)

    client = GeminiClient()
    with pytest.raises(GeminiError):
        asyncio.run(client.generate_json(system_prompt="{}", user_prompt="{}", out_model=None, max_retries=0))

    assert any((r.getMessage() == "gemini_error") or (getattr(r, "event", None) == "gemini_error") for r in caplog.records)


def test_gemini_503_single_attempt_no_retry(monkeypatch, caplog):
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(settings, "GEMINI_MODEL", "gemini-2.5-flash-lite")
    monkeypatch.setattr(settings, "ENV", "development", raising=False)
    caplog.set_level(logging.WARNING)

    calls = {"n": 0}

    class _Resp:
        def __init__(self, status: int, body: str = "{}"):
            self.status_code = status
            self.text = body
            self.headers = {}

        def json(self):
            import json as _json

            return _json.loads(self.text) if self.text else {}

    class _FakeClient:
        async def post(self, *args, **kwargs):
            calls["n"] += 1
            return _Resp(503, "unavailable")

        async def aclose(self):
            return None

    client = GeminiClient(http_client=_FakeClient())

    async def _run():
        await client.generate_json(system_prompt="s", user_prompt="u", out_model=None, max_retries=0, timeout_s=1.0)

    with pytest.raises(GeminiError) as excinfo:
        asyncio.run(_run())
    assert excinfo.value.code == "upstream_unavailable"
    assert calls["n"] == 1
    assert not any("gemini_retry_backoff" in r.getMessage() for r in caplog.records)


def test_gemini_503_then_success_on_retry(monkeypatch):
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(settings, "GEMINI_MODEL", "gemini-2.5-flash-lite")
    monkeypatch.setattr(settings, "ENV", "production", raising=False)

    async def _noop_sleep(_d: float) -> None:
        return None

    monkeypatch.setattr(asyncio, "sleep", _noop_sleep)

    calls = {"n": 0}

    class _Resp:
        def __init__(self, status: int, body: str = "{}"):
            self.status_code = status
            self.text = body
            self.headers = {}

        def json(self):
            return json.loads(self.text) if self.text else {}

    ok_payload = {"candidates": [{"content": {"parts": [{"text": '{"k": 7}'}]}}]}

    class _FakeClient:
        async def post(self, *args, **kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                return _Resp(503, "unavailable")
            return _Resp(200, json.dumps(ok_payload))

        async def aclose(self):
            return None

    class _Out(BaseModel):
        k: int

    client = GeminiClient(http_client=_FakeClient())

    async def _run():
        return await client.generate_json(
            system_prompt="s", user_prompt="u", out_model=_Out, max_retries=1, timeout_s=1.0
        )

    out = asyncio.run(_run())
    assert out.k == 7
    assert calls["n"] == 2


def test_reply_options_rate_limited_still_returns_3(monkeypatch):
    db = _memory_db()
    try:
        u = User(email="me@example.com", hashed_password="x", is_active=True)
        db.add(u)
        db.flush()
        db.add(Profile(user_id=int(u.id), display_name="Me"))
        db.commit()

        app = FastAPI()
        app.include_router(ai_endpoints.router, prefix="/api/v1/ai")

        def _override_db():
            yield db

        def _override_user():
            return u

        app.dependency_overrides[get_db] = _override_db
        app.dependency_overrides[get_current_user] = _override_user

        # Force rate-limit path.
        def _raise(*_args, **_kwargs):
            raise RateLimitExceeded("nope")

        monkeypatch.setattr(ai_endpoints, "enforce_ai_limits", _raise)

        client = TestClient(app)
        r = client.post("/api/v1/ai/reply-options", json={"last_message": "Привіт", "conversation_context": []})
        assert r.status_code == 200
        js = r.json()
        assert isinstance(js.get("options"), list)
        assert len(js["options"]) == 3
        assert all(isinstance(x, str) and x.strip().endswith("?") for x in js["options"])
    finally:
        db.close()

