from datetime import UTC, datetime, timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.deps import get_current_user, get_db
from app.api.v1.endpoints.ai import router
from app.models.message import Message


class DummyUser:
    id = 1


def _build_client_with_db(db) -> TestClient:
    app = FastAPI()
    app.include_router(router, prefix="/api/v1/ai")
    app.dependency_overrides[get_current_user] = lambda: DummyUser()
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app)


class _FakeQuery:
    def __init__(self, rows):
        self._rows = rows

    def filter(self, *_args, **_kwargs):
        return self

    def order_by(self, *_args, **_kwargs):
        return self

    def limit(self, *_args, **_kwargs):
        return self

    def all(self):
        return list(self._rows)


class _FakeDb:
    def __init__(self, rows):
        self._rows = rows

    def query(self, _model):
        return _FakeQuery(self._rows)


def _msg(sender_id: int, receiver_id: int, minutes_ago: int, text: str) -> Message:
    m = Message(sender_id=sender_id, receiver_id=receiver_id, content=text)
    m.created_at = datetime.now(UTC) - timedelta(minutes=minutes_ago)
    return m


def test_combo_wait_has_no_options(monkeypatch):
    from app.api.v1.endpoints import ai as ai_mod

    monkeypatch.setattr(ai_mod, "users_are_matched", lambda *_a, **_k: True)
    monkeypatch.setattr(ai_mod, "is_blocked", lambda *_a, **_k: False)
    monkeypatch.setattr(ai_mod, "track_event", lambda *_a, **_k: None)
    monkeypatch.setattr(ai_mod, "build_memory_context_for_prompt", lambda *_a, **_k: {})

    # Last message from me 10 minutes ago => wait
    db = _FakeDb([_msg(1, 2, 10, "привіт")])
    client = _build_client_with_db(db)
    res = client.post("/api/v1/ai/combo", json={"partner_user_id": 2, "messages": [], "user_profile": {}, "partner_profile": {}})
    assert res.status_code == 200
    payload = res.json()
    assert payload["decision"]["nudge_type"] == "wait"
    assert payload["options"] == []


def test_combo_non_wait_has_three_options(monkeypatch):
    from app.api.v1.endpoints import ai as ai_mod

    monkeypatch.setattr(ai_mod, "users_are_matched", lambda *_a, **_k: True)
    monkeypatch.setattr(ai_mod, "is_blocked", lambda *_a, **_k: False)
    monkeypatch.setattr(ai_mod, "track_event", lambda *_a, **_k: None)
    monkeypatch.setattr(ai_mod, "build_memory_context_for_prompt", lambda *_a, **_k: {})

    # Make it clearly engaged: both ask questions, positive tone; last from them 45m ago.
    rows = [
        _msg(1, 2, 200, "Hey! How was your day today, any highlights?"),
        _msg(2, 1, 170, "Pretty good actually 🙂 What about you, how did your day go?"),
        _msg(1, 2, 120, "Nice! What do you usually like doing in your free time?"),
        _msg(2, 1, 45, "I love travel and exploring new places. Where would you go right now if you could?"),
    ]
    db = _FakeDb(rows)
    client = _build_client_with_db(db)
    res = client.post("/api/v1/ai/combo", json={"partner_user_id": 2, "messages": [], "user_profile": {}, "partner_profile": {}})
    assert res.status_code == 200
    payload = res.json()
    assert payload["decision"]["nudge_type"] != "wait"
    assert len(payload["options"]) == 3
