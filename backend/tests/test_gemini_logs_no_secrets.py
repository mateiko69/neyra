from __future__ import annotations

import asyncio
import logging

import pytest

from app.core.config import settings
from app.services.ai.gemini_client import GeminiClient, redact_gemini_log_text


def test_redact_gemini_log_text_strips_query_key():
    raw = "https://example.com/v1?key=AIzaSyDUMMY_KEY_MATERIAL_1234567890&other=1"
    out = redact_gemini_log_text(raw)
    assert "AIzaSy" not in out
    assert "key=***" in out or "***" in out


def test_gemini_logs_use_safe_url_only(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture):
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "AIzaSyFAKEFAKEFAKEFAKEFAKEFAKEFAKE12", raising=False)
    monkeypatch.setattr(settings, "GEMINI_PRIORITY_SURFACES_ONLY", False, raising=False)

    class FakeResp:
        status_code = 400
        text = '{"error":{"message":"no"}}'

        def json(self):
            return {"error": {"message": "bad"}}

    class FakeClient:
        async def post(self, url, **kwargs):
            # Real client sends key in params, never in URL string — logs must not echo either.
            assert "AIzaSy" not in str(url)
            assert "key=" not in str(url).lower()
            return FakeResp()

        async def aclose(self):
            return None

    client = GeminiClient(http_client=FakeClient())
    caplog.set_level(logging.INFO)
    caplog.set_level(logging.INFO, logger="neyra.ai.gemini")

    async def _call():
        await client.generate_json(
            system_prompt="s",
            user_prompt="u",
            out_model=None,
            timeout_s=1.0,
            max_retries=0,
            surface="admin-debug",
        )

    with pytest.raises(Exception):
        asyncio.run(_call())

    leaked = caplog.text
    for r in caplog.records:
        # Avoid scanning entire LogRecord.__dict__ (can stringify unrelated objects); check emitted text only.
        try:
            msg = r.getMessage()
        except Exception:
            msg = str(getattr(r, "msg", "") or "")
        assert settings.GEMINI_API_KEY not in msg
        assert "AIzaSy" not in msg
    assert settings.GEMINI_API_KEY not in leaked
    assert "AIzaSy" not in leaked
