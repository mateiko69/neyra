from __future__ import annotations

import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.deps import get_admin_actor, get_admin_user, get_db
from app.api.v1.endpoints.admin import router
from app.services.localization import runtime_agent as runtime_agent_mod


class DummyAdmin:
    id = 1
    email = "admin@example.com"


class _FakeDb:
    def query(self, model):
        return self


def _client(*, is_admin: bool = True) -> TestClient:
    app = FastAPI()
    app.include_router(router, prefix="/api/v1/admin")
    if is_admin:
        app.dependency_overrides[get_admin_user] = lambda: DummyAdmin()
        app.dependency_overrides[get_admin_actor] = lambda: DummyAdmin()
    else:
        from fastapi import HTTPException

        app.dependency_overrides[get_admin_user] = lambda: (_ for _ in ()).throw(HTTPException(status_code=403))
        app.dependency_overrides[get_admin_actor] = lambda: (_ for _ in ()).throw(HTTPException(status_code=403))
    app.dependency_overrides[get_db] = lambda: _FakeDb()
    return TestClient(app)


def test_localization_agent_scan_shape(monkeypatch, tmp_path):
    loc = tmp_path / "frontend" / "locales"
    loc.mkdir(parents=True)
    (loc / "en.json").write_text(json.dumps({"k1": "Hello", "k2": "World"}), encoding="utf-8")
    (loc / "uk.json").write_text(json.dumps({"k1": "Привіт"}), encoding="utf-8")

    monkeypatch.setattr(runtime_agent_mod, "_repo_root_from_here", lambda: tmp_path)

    client = _client(is_admin=True)
    res = client.get("/api/v1/admin/localization-agent/scan")
    assert res.status_code == 200
    payload = res.json()
    assert payload["status"] in {"pass", "warning", "fail"}
    summary = payload["summary"]
    assert set(summary.keys()) == {
        "missing_keys",
        "raw_keys_visible",
        "mixed_language_strings",
        "bad_city_cases",
        "unsupported_locales",
    }
    assert isinstance(payload["issues"], list)
    dumped = json.dumps(payload)
    assert "TELEGRAM_BOT_TOKEN" not in dumped
    assert "password" not in dumped.lower()


def test_localization_agent_fix_requires_confirm(monkeypatch, tmp_path):
    loc = tmp_path / "frontend" / "locales"
    loc.mkdir(parents=True)
    (loc / "en.json").write_text("{}", encoding="utf-8")
    (loc / "uk.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(runtime_agent_mod, "_repo_root_from_here", lambda: tmp_path)

    client = _client(is_admin=True)
    res = client.post("/api/v1/admin/localization-agent/fix", json={"mode": "safe"})
    assert res.status_code == 400
    assert res.json()["detail"] == {"error": "confirm_required"}


def test_localization_agent_safe_fix_fills_from_en(monkeypatch, tmp_path):
    loc = tmp_path / "frontend" / "locales"
    loc.mkdir(parents=True)
    (loc / "en.json").write_text(json.dumps({"a": "A", "only_en": "E"}), encoding="utf-8")
    (loc / "uk.json").write_text(json.dumps({"a": "locale.only_en"}), encoding="utf-8")
    monkeypatch.setattr(runtime_agent_mod, "_repo_root_from_here", lambda: tmp_path)

    client = _client(is_admin=True)
    res = client.post("/api/v1/admin/localization-agent/fix", json={"confirm": True, "mode": "safe"})
    assert res.status_code == 200
    body = res.json()
    assert body.get("ok") is True
    uk = json.loads((loc / "uk.json").read_text(encoding="utf-8"))
    assert uk.get("only_en") == "E"
    # Raw placeholder value for key `a` is replaced with the English string for that key.
    assert uk.get("a") == "A"
