from __future__ import annotations

import asyncio

import pytest

from app.core.config import settings
from app.services.ai.diagnostics import clear_gemini_cooldown
from app.services.ai.gemini_client import (
    GeminiClient,
    GeminiError,
    is_gemini_suppressed_after_failure,
    mark_gemini_request_failed,
    reset_gemini_request_scope,
)


def test_generate_json_one_http_post_on_400(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "test-key", raising=False)
    monkeypatch.setattr(settings, "GEMINI_MODEL", "gemini-2.5-flash-lite", raising=False)
    calls = {"n": 0}

    class R:
        status_code = 400
        text = '{"error":{"message":"bad"}}'

        def json(self):
            return {"error": {"message": "bad"}}

    class Fake:
        async def post(self, *a, **k):
            calls["n"] += 1
            return R()

        async def aclose(self):
            return None

    async def run() -> None:
        clear_gemini_cooldown()
        reset_gemini_request_scope()
        c = GeminiClient(http_client=Fake())  # type: ignore[arg-type]
        with pytest.raises(GeminiError):
            await c.generate_json(system_prompt="a", user_prompt="b", out_model=None, timeout_s=1.0)

    asyncio.run(run())
    assert calls["n"] == 1


def test_same_request_suppresses_second_gemini_call(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "test-key", raising=False)
    monkeypatch.setattr(settings, "GEMINI_MODEL", "gemini-2.5-flash-lite", raising=False)
    calls = {"n": 0}

    class R:
        status_code = 400
        text = '{"error":{"message":"nope"}}'

        def json(self):
            return {"error": {"message": "nope"}}

    class Fake:
        async def post(self, *a, **k):
            calls["n"] += 1
            return R()

        async def aclose(self):
            return None

    async def run() -> None:
        clear_gemini_cooldown()
        reset_gemini_request_scope()
        c = GeminiClient(http_client=Fake())  # type: ignore[arg-type]
        with pytest.raises(GeminiError):
            await c.generate_json(system_prompt="a", user_prompt="b", out_model=None, timeout_s=1.0)
        assert calls["n"] == 1
        with pytest.raises(GeminiError) as e2:
            await c.generate_json(system_prompt="a", user_prompt="b", out_model=None, timeout_s=1.0)
        assert e2.value.code == "same_request_gemini_suppressed"
        assert calls["n"] == 1

    asyncio.run(run())


def test_mark_and_reset_request_scope() -> None:
    reset_gemini_request_scope()
    assert not is_gemini_suppressed_after_failure()
    mark_gemini_request_failed()
    assert is_gemini_suppressed_after_failure()
    reset_gemini_request_scope()
    assert not is_gemini_suppressed_after_failure()
