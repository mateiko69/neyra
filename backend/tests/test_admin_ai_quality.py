from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.deps import get_admin_user, get_admin_actor, get_db
from app.api.v1.endpoints.admin import router


class DummyAdmin:
    id = 1
    email = "admin@example.com"


class _FakeQuery:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return list(self._rows)

    def filter(self, *_a, **_k):
        return self


class _FakeDb:
    def __init__(self, events=None, users=None):
        self._events = events or []
        self._users = users or []

    def query(self, model):
        name = getattr(model, "__name__", "")
        if name == "AiInteractionEvent":
            return _FakeQuery(self._events)
        if name == "User":
            return _FakeQuery(self._users)
        return _FakeQuery([])


def _client(db, is_admin: bool) -> TestClient:
    app = FastAPI()
    app.include_router(router, prefix="/api/v1/admin")
    if is_admin:
        app.dependency_overrides[get_admin_user] = lambda: DummyAdmin()
        app.dependency_overrides[get_admin_actor] = lambda: DummyAdmin()
    else:
        from fastapi import HTTPException

        app.dependency_overrides[get_admin_user] = lambda: (_ for _ in ()).throw(HTTPException(status_code=403))
        app.dependency_overrides[get_admin_actor] = lambda: (_ for _ in ()).throw(HTTPException(status_code=403))
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app)


class _Evt:
    def __init__(self, user_id, event_type, metadata_json=None, created_at=None):
        self.user_id = user_id
        self.event_type = event_type
        self.metadata_json = metadata_json or {}
        self.created_at = created_at


def test_admin_can_access_ai_quality():
    db = _FakeDb(events=[_Evt(1, "option_shown"), _Evt(1, "option_selected", {"style": "light"})], users=[])
    client = _client(db, is_admin=True)
    res = client.get("/api/v1/admin/ai-quality")
    assert res.status_code == 200
    payload = res.json()
    assert "summary" in payload
    assert "styles" in payload


def test_non_admin_gets_403():
    db = _FakeDb()
    client = _client(db, is_admin=False)
    res = client.get("/api/v1/admin/ai-quality")
    assert res.status_code == 403

