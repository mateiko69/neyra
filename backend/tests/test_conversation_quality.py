from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.deps import get_current_user, get_db
from app.api.v1.endpoints.ai import router


class DummyUser:
    id = 1


def _client(monkeypatch) -> TestClient:
    # Avoid analytics writes during tests.
    from app.api.v1.endpoints import ai as ai_mod

    monkeypatch.setattr(ai_mod, "track_event", lambda *_a, **_k: None)

    app = FastAPI()
    app.include_router(router, prefix="/api/v1/ai")
    app.dependency_overrides[get_current_user] = lambda: DummyUser()
    app.dependency_overrides[get_db] = lambda: object()
    return TestClient(app)


def test_conversation_quality_hot(monkeypatch):
    client = _client(monkeypatch)
    # Fast back-and-forth, balanced, questions present.
    msgs = [
        {"role": "me", "text": "That sounds fun 😄 what got you into it?", "ts_ms": 1_000},
        {"role": "them", "text": "Honestly my friend dragged me once 😂 what about you?", "ts_ms": 40_000},
        {"role": "me", "text": "Love that. If you had a free weekend, what would you do?", "ts_ms": 70_000},
        {"role": "them", "text": "Either a cozy coffee + walk or a quick trip. You?", "ts_ms": 110_000},
    ]
    res = client.post("/api/v1/ai/conversation-quality", json={"messages": msgs})
    assert res.status_code == 200
    payload = res.json()
    assert payload["status"] == "hot"
    assert payload["score"] >= 75


def test_conversation_quality_cold(monkeypatch):
    client = _client(monkeypatch)
    # One-sided + short, low questions, long gaps.
    msgs = [
        {"role": "me", "text": "Hey 🙂 how’s your day?", "ts_ms": 1_000},
        {"role": "them", "text": "ok", "ts_ms": 10_000_000},
        {"role": "me", "text": "Nice. Doing anything fun this week?", "ts_ms": 10_050_000},
        {"role": "them", "text": "no", "ts_ms": 20_000_000},
    ]
    res = client.post("/api/v1/ai/conversation-quality", json={"messages": msgs})
    assert res.status_code == 200
    payload = res.json()
    assert payload["status"] == "cold"
    assert payload["score"] <= 44

