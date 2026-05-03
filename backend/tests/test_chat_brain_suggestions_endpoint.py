from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.deps import get_current_user, get_db
from app.api.v1.endpoints import ai as ai_module
from app.api.v1.endpoints.ai import router


class DummyUser:
    id = 1


def _client(monkeypatch, *, run_out: dict, ai_enabled: bool = True):
    app = FastAPI()
    app.include_router(router, prefix="/api/v1/ai")

    def _db():
        return MagicMock()

    app.dependency_overrides[get_current_user] = lambda: DummyUser()
    app.dependency_overrides[get_db] = _db

    monkeypatch.setattr(ai_module.settings, "ENABLE_AI_SUGGESTIONS", ai_enabled)
    monkeypatch.setattr(ai_module, "is_blocked", lambda _db, _a, _b: False)
    monkeypatch.setattr(ai_module, "users_are_matched", lambda _db, _a, _b: True)
    monkeypatch.setattr(ai_module, "enforce_ai_limits", lambda _db, _uid: None)
    monkeypatch.setattr(ai_module, "track_event", lambda *_a, **_k: None)
    monkeypatch.setattr(
        "app.services.ai.chat_brain_suggestions.run_chat_brain_suggestions",
        lambda _db, user_id, body, plan_tier="free", **kwargs: run_out,
    )

    return TestClient(app)


def test_chat_brain_suggestions_returns_variants(monkeypatch):
    run_out = {
        "ok": True,
        "variants": {"light": "hi", "flirty": "hey", "deep": "hello"},
        "coaching": {"action": "write_now"},
        "ui": {"suggestions_visible": True, "wait_phase": None},
        "recommended_variant": "light",
        "recommendation_reason": "easy_not_spam",
        "variant_insights": {
            "light": {"risk": "safe", "tip_key": "easy_open"},
            "flirty": {"risk": "neutral", "tip_key": "matches_mood"},
            "deep": {"risk": "neutral", "tip_key": "fits_context"},
        },
        "meta": {"mode": "opener", "language": "uk", "regenerate_variant": None, "ai_used": True},
    }
    client = _client(monkeypatch, run_out=run_out)

    res = client.post(
        "/api/v1/ai/chat-brain/suggestions",
        json={
            "partner_user_id": 9,
            "mode": "opener",
            "tone": "auto",
            "language": "uk",
        },
    )

    assert res.status_code == 200
    payload = res.json()
    assert payload["ok"] is True
    assert payload["variants"]["light"] == "hi"
    assert payload["variants"]["flirty"] == "hey"
    assert payload["variants"]["deep"] == "hello"
    assert payload["meta"]["mode"] == "opener"
    assert payload["recommended_variant"] == "light"
    assert payload["coaching"]["action"] == "write_now"


def test_chat_brain_suggestions_disabled_returns_200_fallback(monkeypatch):
    run_out = {"ok": True, "variants": {}, "meta": {}}
    client = _client(monkeypatch, run_out=run_out, ai_enabled=False)

    res = client.post(
        "/api/v1/ai/chat-brain/suggestions",
        json={"partner_user_id": 9, "mode": "opener", "tone": "auto", "language": "en"},
    )

    assert res.status_code == 200
    body = res.json()
    assert body.get("ok") is True
    assert body.get("fallback") is True
    v = body.get("variants") or {}
    assert str(v.get("light") or "").strip()


def test_chat_brain_suggestions_not_matched_returns_403(monkeypatch):
    run_out = {"ok": True, "variants": {}, "meta": {}}
    client = _client(monkeypatch, run_out=run_out)
    monkeypatch.setattr(ai_module, "users_are_matched", lambda _db, _a, _b: False)

    res = client.post(
        "/api/v1/ai/chat-brain/suggestions",
        json={"partner_user_id": 9, "mode": "reply", "tone": "auto", "language": "en"},
    )

    assert res.status_code == 403
