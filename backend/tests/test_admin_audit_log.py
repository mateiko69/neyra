from __future__ import annotations

from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.deps import get_admin_user, get_admin_actor
from app.api.v1.endpoints.admin import router as admin_router
from app.db.session import SessionLocal
from app.services.analytics import track_event


class DummyAdmin:
    id = 999
    email = "admin@example.com"


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(admin_router, prefix="/api/v1/admin")
    app.dependency_overrides[get_admin_user] = lambda: DummyAdmin()
    app.dependency_overrides[get_admin_actor] = lambda: DummyAdmin()
    return TestClient(app)


def _seed_admin_action(action: str, payload: dict | None = None):
    db = SessionLocal()
    try:
        event = track_event(db, "admin_action", user_id=999, payload={"action": action, **(payload or {})})
        return int(event.id)
    finally:
        db.close()


def test_audit_log_endpoint_shape():
    action = f"audit_shape_{uuid4().hex}"
    _seed_admin_action(action, {"target_user_id": 123, "status": "success", "days": 7})
    res = _client().get("/api/v1/admin/audit-log", params={"action_type": action})
    assert res.status_code == 200
    payload = res.json()
    assert set(payload.keys()) == {"items", "total"}
    assert payload["total"] == 1
    item = payload["items"][0]
    assert set(item.keys()) == {"id", "created_at", "admin_user_id", "action", "target_type", "target_id", "status", "metadata"}
    assert item["admin_user_id"] == 999
    assert item["action"] == action
    assert item["target_id"] == "123"
    assert item["status"] == "success"


def test_audit_log_pagination_works():
    action = f"audit_page_{uuid4().hex}"
    ids = [_seed_admin_action(action, {"status": "success", "seq": i}) for i in range(3)]
    res = _client().get("/api/v1/admin/audit-log", params={"action_type": action, "limit": 2, "offset": 1})
    assert res.status_code == 200
    payload = res.json()
    assert payload["total"] == 3
    assert len(payload["items"]) == 2
    assert [row["id"] for row in payload["items"]] == list(reversed(ids))[1:3]


def test_audit_log_filter_works():
    action_a = f"audit_filter_a_{uuid4().hex}"
    action_b = f"audit_filter_b_{uuid4().hex}"
    _seed_admin_action(action_a, {"status": "success"})
    _seed_admin_action(action_b, {"status": "success"})
    res = _client().get("/api/v1/admin/audit-log", params={"action_type": action_a})
    assert res.status_code == 200
    payload = res.json()
    assert payload["total"] == 1
    assert payload["items"][0]["action"] == action_a


def test_audit_log_secrets_redacted():
    action = f"audit_secret_{uuid4().hex}"
    _seed_admin_action(
        action,
        {
            "api_key": "BAD",
            "nested": {"token": "NOPE"},
            "note": "password=HIDDEN private chat raw_messages",
        },
    )
    res = _client().get("/api/v1/admin/audit-log", params={"action_type": action})
    assert res.status_code == 200
    raw = res.text.lower()
    assert "bad" not in raw
    assert "nope" not in raw
    assert "hidden" not in raw
    assert "api_key" not in raw
    assert "password" not in raw
    assert "private chat" not in raw
    assert "raw_messages" not in raw
