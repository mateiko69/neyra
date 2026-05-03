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


def test_conversation_quality_overview_shape():
    c = _client()
    res = c.get("/api/v1/admin/conversation-quality/overview?period=today")
    assert res.status_code == 200
    j = res.json()
    assert j["period"] in {"today", "7d", "30d"}
    assert "summary" in j and "styles" in j and "issues" in j
    s = j["summary"]
    for k in [
        "ai_options_shown",
        "ai_options_selected",
        "selection_rate",
        "edited_rate",
        "message_sent_after_ai",
        "partner_reply_after_ai",
        "partner_reply_rate",
        "duplicate_rate",
        "stall_detected_count",
        "revive_used_count",
        "meeting_suggested_count",
        "meeting_rejected_count",
    ]:
        assert k in s
    assert set(j["styles"].keys()) >= {"light", "flirty", "deep"}
    assert "recommendations" in j and isinstance(j["recommendations"], list)
    assert any("recompute" in str(x).lower() for x in j["recommendations"])


def test_conversation_quality_issues_shape_and_no_private_content():
    c = _client()
    res = c.get("/api/v1/admin/conversation-quality/issues")
    assert res.status_code == 200
    j = res.json()
    for k in [
        "duplicate_reply_issues",
        "high_edit_rate",
        "low_reply_rate",
        "meeting_too_early",
        "stalled_chats_count",
    ]:
        assert k in j
    # No raw message content.
    assert "content" not in str(j).lower()

