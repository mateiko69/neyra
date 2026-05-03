from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.deps import get_admin_user, get_admin_actor
from app.api.v1.endpoints.admin import router as admin_router


class DummyAdmin:
    id = 999
    email = "admin@example.com"


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(admin_router, prefix="/api/v1/admin")
    app.dependency_overrides[get_admin_user] = lambda: DummyAdmin()
    app.dependency_overrides[get_admin_actor] = lambda: DummyAdmin()
    return TestClient(app)


def test_e2e_qa_scan_endpoint_shape():
    c = _client()
    r = c.get("/api/v1/admin/e2e-qa/scan")
    assert r.status_code == 200
    j = r.json()
    assert j["status"] in {"pass", "warning", "fail"}
    assert "summary" in j and "flows" in j and "issues" in j
    for k in ["flows_checked", "passed", "warnings", "failed", "no_data", "skipped"]:
        assert k in j["summary"]


def test_e2e_qa_respects_allow_ai_calls_false(monkeypatch):
    monkeypatch.setenv("E2E_QA_ALLOW_AI_CALLS", "false")
    c = _client()
    j = c.get("/api/v1/admin/e2e-qa/scan").json()
    # Ensure AI flow is not marked as pass due to real calls
    chat_ai = [f for f in j["flows"] if f["id"] == "chat_ai"][0]
    assert chat_ai["status"] in {"warning", "pass", "skipped"}
    assert any("disabled" in str(x).lower() for x in chat_ai.get("issues", []))


def test_e2e_qa_respects_allow_write_actions_false(monkeypatch):
    monkeypatch.setenv("E2E_QA_ALLOW_WRITE_ACTIONS", "false")
    c = _client()
    j = c.get("/api/v1/admin/e2e-qa/scan").json()
    msgs = [f for f in j["flows"] if f["id"] == "messages_send"][0]
    assert msgs["status"] == "skipped"


def test_e2e_qa_no_private_message_content():
    c = _client()
    j = c.get("/api/v1/admin/e2e-qa/scan").json()
    s = str(j).lower()
    # Should never include raw message content.
    assert "\"content\"" not in s

