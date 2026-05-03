from __future__ import annotations

import asyncio

import pytest

from app.services.ai.gemini_client import GeminiClient, GeminiError, reset_gemini_request_scope
from app.services.ai.diagnostics import clear_gemini_cooldown
from app.services.ai.gemini_global_gate import reset_gemini_global_failure_memory


class _FakeResp:
    def __init__(self, status_code: int, text: str = ""):
        self.status_code = int(status_code)
        self.text = text

    def json(self):  # noqa: ANN001
        return {"error": {"message": self.text}}


class _FakeHttp:
    def __init__(self):
        self.calls = 0

    async def post(self, *args, **kwargs):  # noqa: ANN001
        self.calls += 1
        return _FakeResp(429, "quota exhausted")


def test_gemini_429_sets_cooldown_and_skips_next_call(monkeypatch: pytest.MonkeyPatch) -> None:
    async def run() -> None:
        clear_gemini_cooldown()
        # Ensure Gemini is "enabled" for the client.
        import app.core.config as cfg

        monkeypatch.setattr(cfg.settings, "GEMINI_API_KEY", "x")
        fake = _FakeHttp()
        client = GeminiClient(http_client=fake)  # type: ignore[arg-type]

        # First call hits upstream and fails with quota_exhausted.
        with pytest.raises(GeminiError) as e:
            await client.generate_json(system_prompt="x", user_prompt="y", out_model=None, timeout_s=1.0, max_retries=0)
        assert str(e.value.code) in {"quota_exhausted", "cooldown_active"}
        assert fake.calls == 1

        # Isolate Google's quota cooldown from same-request / global-failure guards.
        reset_gemini_request_scope()
        reset_gemini_global_failure_memory()

        # Second call should be blocked by cooldown (no extra upstream call).
        with pytest.raises(GeminiError) as e2:
            await client.generate_json(system_prompt="x", user_prompt="y", out_model=None, timeout_s=1.0, max_retries=0)
        assert e2.value.code == "cooldown_active"
        assert fake.calls == 1
        clear_gemini_cooldown()

    asyncio.run(run())

