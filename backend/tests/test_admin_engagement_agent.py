from __future__ import annotations

import json

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


def test_engagement_overview_has_core_metrics():
    c = _client()
    r = c.get("/api/v1/admin/engagement/overview")
    assert r.status_code == 200
    j = r.json()
    for k in [
        "first_message_rate",
        "reply_rate",
        "dead_chats_count",
        "chats_no_first_message_count",
        "stale_chats_sample_count",
        "issues",
        "total_matches",
    ]:
        assert k in j
    assert isinstance(j["first_message_rate"], (int, float))
    assert isinstance(j["reply_rate"], (int, float))
    assert isinstance(j["issues"], list)


def test_engagement_targets_lists_pairs_without_content():
    c = _client()
    r = c.get("/api/v1/admin/engagement/targets")
    assert r.status_code == 200
    j = r.json()
    assert "counts" in j and "no_first_message" in j and "stale_chats" in j
    raw = json.dumps(j, ensure_ascii=False).lower()
    assert '"content"' not in raw
    assert "message_id" not in raw


def test_engagement_generate_invalid_kind():
    c = _client()
    r = c.post("/api/v1/admin/engagement/generate", json={"match_id": 1, "kind": "invalid"})
    assert r.status_code == 400


def test_engagement_generate_unknown_match():
    c = _client()
    r = c.post("/api/v1/admin/engagement/generate", json={"match_id": 999999999, "kind": "tones", "use_ai": False})
    assert r.status_code == 404


def test_engagement_actions_shape_and_no_message_bodies():
    c = _client()
    r = c.get("/api/v1/admin/engagement/actions", params={"use_ai": False})
    assert r.status_code == 200
    j = r.json()
    assert "actions" in j and isinstance(j["actions"], list)
    assert "candidates_summary" in j
    raw = json.dumps(j, ensure_ascii=False).lower()
    assert "message_id" not in raw
    assert '"content"' not in raw
    for a in j["actions"][:12]:
        assert "type" in a and "match_id" in a
        assert isinstance(a["type"], str) and str(a["match_id"]).isdigit()


def test_engagement_execute_default_simulate_logs_without_send():
    c = _client()
    r = c.post("/api/v1/admin/engagement/execute", json={})
    assert r.status_code == 200
    j = r.json()
    assert j.get("ok") is True
    assert j.get("simulate") is True
    assert "delivered" not in str(j).lower() or "no messages" in str(j.get("message", "")).lower()


def test_engagement_execute_requires_confirm_when_not_simulating():
    c = _client()
    r = c.post("/api/v1/admin/engagement/execute", json={"simulate": False})
    assert r.status_code == 400


def test_telegram_engagement_renders_with_mock_backend():
    from importlib.machinery import SourceFileLoader
    from importlib.util import module_from_spec, spec_from_loader
    from pathlib import Path
    import sys

    script = Path(__file__).resolve().parents[1] / "scripts" / "telegram_admin_bot.py"
    loader = SourceFileLoader("telegram_admin_bot_eng", str(script))
    spec = spec_from_loader("telegram_admin_bot_eng", loader)
    assert spec is not None
    bot = module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["telegram_admin_bot_eng"] = bot
    spec.loader.exec_module(bot)  # type: ignore[attr-defined]

    class _FakeBackend:
        def request(self, method: str, path: str, json_body: dict | None = None):
            if path.endswith("/engagement/overview"):
                return {
                    "first_message_rate": 0.17,
                    "reply_rate": 0.12,
                    "dead_chats_count": 3,
                    "chats_no_first_message_count": 2,
                    "stale_chats_sample_count": 1,
                    "avg_time_to_first_message_hours": 4.5,
                    "revive_success_rate": 0.25,
                }
            if path.endswith("/engagement/targets"):
                return {
                    "counts": {"no_first_message": 1, "dead_stale": 1, "weak_match": 0},
                    "no_first_message": [{"match_id": 9, "user_a_name": "A", "user_b_name": "B"}],
                    "stale_chats": [{"match_id": 8, "user_a_name": "C", "user_b_name": "D", "last_message_at": "2026-01-01T00:00:00+00:00"}],
                    "weak_matches": [],
                }
            if path.endswith("/engagement/actions"):
                return {
                    "actions": [
                        {"type": "ai_message_suggestion", "match_id": 9, "user_id": 1, "suggestions": ["a", "b", "c"]},
                        {"type": "revive_chat", "match_id": 8, "suggestion": "Hello again"},
                    ],
                    "candidates_summary": {"no_first_message": 1, "dead_stale": 1, "weak_match": 0},
                }
            if method == "POST" and "/engagement/generate" in path and json_body:
                k = str(json_body.get("kind") or "")
                mid = int(json_body.get("match_id") or 0)
                if k == "tones":
                    return {
                        "ok": True,
                        "match_id": mid,
                        "kind": "tones",
                        "pair_label": "A · B",
                        "tones": {"light": "L", "flirty": "F", "deep": "D"},
                        "ai_used": False,
                    }
                if k == "opener":
                    return {"ok": True, "match_id": mid, "kind": "opener", "pair_label": "A · B", "opener": "Hi", "ai_used": False}
                if k == "revive":
                    return {
                        "ok": True,
                        "match_id": mid,
                        "kind": "revive",
                        "pair_label": "C · D",
                        "revive_message": "Again?",
                        "last_message_at": "2026-01-01T00:00:00+00:00",
                        "ai_used": False,
                    }
                return {"ok": False}
            return {}

    bot.backend = _FakeBackend()
    bot.admin_lang[1] = "en"

    txt, _kb = bot.render_engagement_overview(1)
    assert "17%" in txt or "first message" in txt.lower()
    assert "12%" in txt or "reply" in txt.lower()

    txt2, _kb2 = bot.render_engagement_ai_suggestions(1)
    assert "9" in txt2 and "A" in txt2 and "B" in txt2

    txt3, kb3 = bot.render_engagement_generated_detail(1, "tones", {"ok": True, "match_id": 9, "pair_label": "A · B", "tones": {"light": "L", "flirty": "F", "deep": "D"}, "ai_used": False}, "m:engagement", "e:gt:a:9")
    assert "Light" in txt3 and "L" in txt3
    assert kb3 and "e:gt:a:9" in (kb3[0][0].get("callback_data") or "")
