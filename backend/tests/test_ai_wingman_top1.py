"""Top-1 wingman stack: stage engine, strategy, memory API (privacy-safe aggregates)."""

from __future__ import annotations

from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.deps import get_current_user, get_db
from app.api.v1.endpoints import ai as ai_module
from app.api.v1.endpoints.ai import router
from app.services.ai.conversation.conversation_stage_engine import detect_stage
from app.services.ai.conversation.dating_strategy_engine import plan_dating_strategy


class DummyUser:
    id = 501


def test_detect_stage_opener_for_fresh_thread():
    out = detect_stage([{"role": "me", "text": "Hey!"}, {"role": "partner", "text": "Hi there"}])
    assert out["stage"] == "opener"
    assert "mutuality_score" in out and "energy_score" in out


def test_strategy_suggest_meet_when_meeting_ready():
    msgs = []
    for i in range(10):
        msgs.append({"role": "me" if i % 2 == 0 else "partner", "text": f"Line {i} with a bit more content here?", "created_at": None})
    stage_info = {
        "stage": "meeting_ready",
        "mutuality_score": 0.62,
        "energy_score": 0.55,
    }
    strat = plan_dating_strategy(
        stage_info=stage_info,
        stage_messages=msgs,
        last_text_role="partner",
        hours_since_last_text=0.5,
        run_generation=True,
        trail_me=0,
    )
    assert strat["next_action"] == "suggest_meet"


def test_memory_context_endpoint_no_premium_gate(monkeypatch):
    app = FastAPI()
    app.include_router(router, prefix="/api/v1/ai")

    def _db():
        return MagicMock()

    app.dependency_overrides[get_current_user] = lambda: DummyUser()
    app.dependency_overrides[get_db] = _db

    monkeypatch.setattr(ai_module, "update_user_ai_memory", lambda **kwargs: None)
    monkeypatch.setattr(
        ai_module,
        "get_personalization_context",
        lambda db, user_id: {
            "summary_json": {"tone_preference": "playful", "interests": ["coffee"], "avoid": [], "flirt_level": 0.4, "languages": [], "notes": []},
            "updated_at": "2026-01-01T00:00:00+00:00",
        },
    )

    client = TestClient(app)
    res = client.get("/api/v1/ai/memory/context")
    assert res.status_code == 200
    data = res.json()
    assert data.get("schema") == "wingman_v1"
    assert data["summary_json"]["tone_preference"] == "playful"
    assert data.get("byte_length", 0) > 0


def test_memory_event_rejects_unknown_type(monkeypatch):
    app = FastAPI()
    app.include_router(router, prefix="/api/v1/ai")

    def _db():
        return MagicMock()

    app.dependency_overrides[get_current_user] = lambda: DummyUser()
    app.dependency_overrides[get_db] = _db

    client = TestClient(app)
    res = client.post("/api/v1/ai/memory/event", json={"event_type": "not_a_real_event", "metadata": {}})
    assert res.status_code == 400


def test_memory_event_accepts_option_selected(monkeypatch):
    app = FastAPI()
    app.include_router(router, prefix="/api/v1/ai")

    mock_db = MagicMock()

    def _db():
        yield mock_db

    app.dependency_overrides[get_current_user] = lambda: DummyUser()
    app.dependency_overrides[get_db] = _db

    called = {}

    def _capture(db, **kwargs):
        called.update(kwargs)

    monkeypatch.setattr(ai_module, "log_ai_event", _capture)

    client = TestClient(app)
    res = client.post(
        "/api/v1/ai/memory/event",
        json={"event_type": "option_selected", "partner_user_id": 9, "metadata": {"style": "flirty"}},
    )
    assert res.status_code == 200
    assert called.get("event_type") == "option_selected"
    assert called.get("partner_user_id") == 9
