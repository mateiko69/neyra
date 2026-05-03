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


def test_match_quality_overview_shape():
    c = _client()
    res = c.get("/api/v1/admin/match-quality/overview")
    assert res.status_code == 200
    j = res.json()
    for k in [
        "total_matches",
        "matches_today",
        "mutual_like_rate",
        "average_compatibility_score",
        "weak_matches_count",
        "dead_chats_count",
        "active_chats_count",
        "reply_rate",
        "ai_match_coverage_rate",
        "top_match_issues",
    ]:
        assert k in j


def test_weak_matches_has_no_private_message_text():
    c = _client()
    res = c.get("/api/v1/admin/match-quality/weak-matches")
    assert res.status_code == 200
    arr = res.json()
    assert isinstance(arr, list)
    # Must not include raw message content fields.
    for row in arr[:20]:
        assert "content" not in row
        assert "messages" not in row
        assert "raw_messages" not in row


def test_dead_chats_has_no_private_message_text():
    c = _client()
    res = c.get("/api/v1/admin/match-quality/dead-chats")
    assert res.status_code == 200
    arr = res.json()
    assert isinstance(arr, list)
    for row in arr[:20]:
        assert "content" not in row
        assert "messages" not in row
        assert "raw_messages" not in row


def test_match_quality_recompute_requires_confirm():
    c = _client()
    res = c.post("/api/v1/admin/match-quality/recompute", json={})
    assert res.status_code == 400

