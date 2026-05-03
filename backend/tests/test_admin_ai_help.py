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


def test_ai_help_endpoint_shape_and_langs():
    c = _client()
    r = c.get("/api/v1/admin/ai-help/premium", params={"lang": "en"})
    assert r.status_code == 200
    j = r.json()
    for k in [
        "section",
        "title",
        "summary",
        "what_to_watch",
        "recommended_actions",
        "risk_notes",
        "next_best_action",
        "explanation",
        "issues",
        "suggestions",
    ]:
        assert k in j
    assert isinstance(j["explanation"], str)
    assert isinstance(j["issues"], list)
    assert isinstance(j["suggestions"], list)
    r2 = c.get("/api/v1/admin/ai-help/premium", params={"lang": "uk"})
    assert r2.status_code == 200
    j2 = r2.json()
    assert j2["summary"] != j["summary"] or j2["title"] != j["title"]


def test_ai_help_post_returns_analysis_shape():
    c = _client()
    r = c.post("/api/v1/admin/ai-help", json={"section": "premium", "lang": "en"})
    assert r.status_code == 200
    j = r.json()
    assert set(j.keys()) >= {"explanation", "issues", "suggestions", "section", "title"}
    assert isinstance(j["explanation"], str)
    assert isinstance(j["issues"], list)
    assert isinstance(j["suggestions"], list)


def test_ai_help_unknown_section_generic():
    c = _client()
    j = c.get("/api/v1/admin/ai-help/unknown_section", params={"lang": "en"}).json()
    assert j["section"] == "unknown_section"
    assert "Control Center" in j["summary"]


def test_ai_help_no_secrets_or_private_content():
    c = _client()
    j = c.get("/api/v1/admin/ai-help/system", params={"lang": "en"}).json()
    s = str(j).lower()
    assert "api_key" not in s
    assert "authorization" not in s
    assert "\"content\"" not in s


def test_ai_help_engagement_section():
    c = _client()
    r = c.get("/api/v1/admin/ai-help/engagement", params={"lang": "en"})
    assert r.status_code == 200
    j = r.json()
    assert j["section"] == "engagement"
    summ = str(j.get("summary", "")).lower()
    assert "match" in summ or "engagement" in summ or "why" in summ
    wt = j.get("what_to_watch") or []
    assert isinstance(wt, list) and len(wt) >= 2

