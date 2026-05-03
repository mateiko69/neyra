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


def _msg(sender_id: int, receiver_id: int, minutes_ago: int) -> Message:
    m = Message(sender_id=sender_id, receiver_id=receiver_id, content="hi")
    m.created_at = datetime.now(UTC) - timedelta(minutes=minutes_ago)
    return m


def test_wait_if_user_sent_last_under_30_min(monkeypatch):
    # Bypass match/block checks.
    from app.api.v1.endpoints import ai as ai_mod

    monkeypatch.setattr(ai_mod, "users_are_matched", lambda *_a, **_k: True)
    monkeypatch.setattr(ai_mod, "is_blocked", lambda *_a, **_k: False)
    monkeypatch.setattr(ai_mod, "track_event", lambda *_a, **_k: None)

    db = _FakeDb([_msg(1, 2, minutes_ago=10)])
    client = _build_client_with_db(db)
    res = client.post(
        "/api/v1/ai/timing-decision",
        json={"partner_user_id": 2, "messages": [], "interest_stage": "engaged", "mutuality_score": 80, "stall_score": 0},
    )
    assert res.status_code == 200
    payload = res.json()
    assert payload["nudge_type"] == "wait"
    assert payload["should_send_now"] is False


def test_reengage_if_no_reply_for_12h(monkeypatch):
    from app.api.v1.endpoints import ai as ai_mod

    monkeypatch.setattr(ai_mod, "users_are_matched", lambda *_a, **_k: True)
    monkeypatch.setattr(ai_mod, "is_blocked", lambda *_a, **_k: False)
    monkeypatch.setattr(ai_mod, "track_event", lambda *_a, **_k: None)

    # last message is older than 12h and from viewer
    db = _FakeDb([_msg(1, 2, minutes_ago=12 * 60 + 5)])
    client = _build_client_with_db(db)
    res = client.post(
        "/api/v1/ai/timing-decision",
        json={"partner_user_id": 2, "messages": [], "interest_stage": "warming", "mutuality_score": 40, "stall_score": 0},
    )
    assert res.status_code == 200
    payload = res.json()
    assert payload["nudge_type"] == "reengage"
    assert payload["should_send_now"] is True


def test_revive_if_stall_high(monkeypatch):
    from app.api.v1.endpoints import ai as ai_mod

    monkeypatch.setattr(ai_mod, "users_are_matched", lambda *_a, **_k: True)
    monkeypatch.setattr(ai_mod, "is_blocked", lambda *_a, **_k: False)
    monkeypatch.setattr(ai_mod, "track_event", lambda *_a, **_k: None)

    db = _FakeDb([_msg(2, 1, minutes_ago=60)])
    client = _build_client_with_db(db)
    res = client.post(
        "/api/v1/ai/timing-decision",
        json={"partner_user_id": 2, "messages": [], "interest_stage": "warming", "mutuality_score": 30, "stall_score": 80},
    )
    assert res.status_code == 200
    payload = res.json()
    assert payload["nudge_type"] == "revive"
    assert payload["should_send_now"] is True


def test_now_if_engaged_and_mutuality_high(monkeypatch):
    from app.api.v1.endpoints import ai as ai_mod

    monkeypatch.setattr(ai_mod, "users_are_matched", lambda *_a, **_k: True)
    monkeypatch.setattr(ai_mod, "is_blocked", lambda *_a, **_k: False)
    monkeypatch.setattr(ai_mod, "track_event", lambda *_a, **_k: None)

    db = _FakeDb([_msg(2, 1, minutes_ago=45)])
    client = _build_client_with_db(db)
    res = client.post(
        "/api/v1/ai/timing-decision",
        json={"partner_user_id": 2, "messages": [], "interest_stage": "engaged", "mutuality_score": 65, "stall_score": 0},
    )
    assert res.status_code == 200
    payload = res.json()
    assert payload["nudge_type"] == "now"
    assert payload["should_send_now"] is True

