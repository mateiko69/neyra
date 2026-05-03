from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.deps import get_admin_actor, get_admin_user, get_db
from app.api.v1.endpoints import admin as admin_mod
from app.db.base import Base


class DummyAdmin:
    id = 999
    email = "admin@example.com"


def _client() -> TestClient:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    import app.models  # noqa: F401
    Base.metadata.create_all(engine)

    def _get_db_override():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app = FastAPI()
    app.include_router(admin_mod.router, prefix="/api/v1/admin")
    app.dependency_overrides[get_admin_user] = lambda: DummyAdmin()
    app.dependency_overrides[get_admin_actor] = lambda: DummyAdmin()
    app.dependency_overrides[get_db] = _get_db_override
    return TestClient(app)


def test_full_analysis_shape_and_score():
    client = _client()
    res = client.get("/api/v1/admin/system/full-analysis")
    assert res.status_code == 200
    j = res.json()
    assert j["status"] in {"healthy", "warning", "critical"}
    assert 0 <= int(j["score"]) <= 100
    assert isinstance(j["generated_at"], str) and j["generated_at"]
    assert isinstance(j["owner_summary"], str) and j["owner_summary"]
    for key in ("top_issues", "top_recommendations", "next_best_actions", "quick_actions", "e2e_warning_details", "localization_top_locales"):
        assert isinstance(j[key], list)
    assert len(j["top_issues"]) <= 5
    assert len(j["top_recommendations"]) <= 5
    assert len(j["next_best_actions"]) <= 5
    assert len(j["quick_actions"]) <= 5
    assert isinstance(j["sections"], list)
    for sec in j["sections"]:
        assert sec["id"]
        assert sec["title"]
        assert sec["status"] in {"healthy", "warning", "critical"}
        assert isinstance(sec["summary"], str)
        assert isinstance(sec["details"], list)
        assert isinstance(sec["issues"], list)
        assert isinstance(sec["recommended_actions"], list)


def test_full_analysis_no_raw_error_dump_or_secrets():
    client = _client()
    raw = client.get("/api/v1/admin/system/full-analysis").text.lower()
    assert "last_10_errors" not in raw
    assert "bearer " not in raw
    assert "api_key=" not in raw


def test_full_analysis_recompute_quick_action_present(monkeypatch):
    monkeypatch.setattr(admin_mod, "admin_backups_list", lambda *a, **k: [])
    res = _client().get("/api/v1/admin/system/full-analysis")
    assert res.status_code == 200
    qa = res.json().get("quick_actions") or []
    assert any(x.get("callback_data") == "m:match_quality_recompute" for x in qa)


def test_full_analysis_score_reaches_95_when_subsystems_healthy(monkeypatch):
    """E2E informational skips should not cap the owner score when everything else is green."""

    def _e2e_ok(*a, **k):
        return {
            "status": "pass",
            "summary": {"flows_checked": 5, "passed": 5, "warnings": 0, "failed": 0, "no_data": 2, "skipped": 3},
            "flows": [],
            "issues": [],
            "meta": {},
        }

    def _menu_ok(admin_actor):
        return {
            "status": "pass",
            "summary": {
                "menus_checked": 1,
                "buttons_checked": 1,
                "callbacks_checked": 1,
                "missing_handlers": 0,
                "missing_translations": 0,
                "unsafe_actions": 0,
                "render_errors": 0,
            },
        }

    def _loc_cov(*a, **k):
        return {
            "locales": [
                {
                    "code": "en",
                    "coverage": 100,
                    "coverage_present_pct": 100,
                    "total_keys": 200,
                    "translated_keys": 200,
                    "missing": 0,
                    "identical_to_en": 0,
                    "empty": 0,
                    "raw_keys": 0,
                    "top_missing_keys": [],
                    "top_identical_to_en_keys": [],
                    "top_untranslated_keys": [],
                    "core_overlay_keys": 0,
                },
                {
                    "code": "uk",
                    "coverage": 88,
                    "coverage_present_pct": 95,
                    "total_keys": 200,
                    "translated_keys": 176,
                    "missing": 10,
                    "identical_to_en": 14,
                    "empty": 0,
                    "raw_keys": 0,
                    "top_missing_keys": [],
                    "top_identical_to_en_keys": [],
                    "top_untranslated_keys": [],
                    "core_overlay_keys": 20,
                },
            ],
            "summary": {
                "missing_keys_total": 10,
                "raw_value_leaks_total": 0,
                "en_fallback_keys_total": 14,
                "unique_translated_keys_total": 176,
            },
            "reference_key_count": 200,
            "core_ui_overlay_locales": ["uk"],
        }

    def _growth_healthy(period, admin_actor, db):
        return {
            "period": period,
            "acquisition": {"new_users": 50, "signups_by_locale": {"uk": 12}, "signups_by_country": {}, "top_sources": {}},
            "activation": {
                "profile_completed_rate": 0.86,
                "photo_added_rate": 0.82,
                "first_like_rate": 0.45,
                "first_match_rate": 0.32,
                "first_message_rate": 0.35,
            },
            "retention": {"active_users": 40, "returning_users": 28, "day_1_retention_best_effort": 0.42, "dead_users_count": 0},
            "monetization": {
                "premium_users": 2,
                "trial_users": 1,
                "paywall_views": 4,
                "premium_conversion_rate": 0.08,
                "top_paywall_sources": {},
            },
            "recommendations": [],
            "onboarding": {
                "bottlenecks": {
                    "missing_photo_count": 2,
                    "thin_bio_count": 3,
                    "verification_pending_count": 0,
                    "verification_none_after_complete_count": 1,
                },
                "rates": {"photo_added_rate": 0.82, "thin_bio_rate": 0.12},
            },
        }

    def _mq_healthy(admin_actor, db):
        return {
            "total_matches": 10,
            "matches_today": 1,
            "mutual_like_rate": 0.2,
            "average_compatibility_score": 72.0,
            "weak_matches_count": 0,
            "dead_chats_count": 0,
            "active_chats_count": 3,
            "reply_rate": 0.55,
            "ai_match_coverage_rate": 0.4,
            "top_match_issues": [],
        }

    def _cq_healthy(period, admin_actor, db):
        return {
            "period": period,
            "summary": {
                "ai_options_shown": 10,
                "ai_options_selected": 6,
                "selection_rate": 0.6,
                "edited_rate": 0.1,
                "message_sent_after_ai": 8,
                "partner_reply_after_ai": 4,
                "partner_reply_rate": 0.5,
                "duplicate_rate": 0.02,
                "stall_detected_count": 0,
                "revive_used_count": 0,
                "meeting_suggested_count": 0,
                "meeting_rejected_count": 0,
            },
            "styles": {"light": {}, "flirty": {}, "deep": {}},
            "issues": [],
            "recommendations": [],
        }

    monkeypatch.setattr("app.services.localization.coverage.compute_localization_coverage", _loc_cov)
    monkeypatch.setattr(admin_mod, "localization_quality", lambda admin_actor: {"summary": {}})
    monkeypatch.setattr(admin_mod, "admin_growth_overview", _growth_healthy)
    monkeypatch.setattr(admin_mod, "admin_match_quality_overview", _mq_healthy)
    monkeypatch.setattr(admin_mod, "admin_conversation_quality_overview", _cq_healthy)
    monkeypatch.setattr(
        "app.services.localization.runtime_agent.run_localization_agent_scan",
        lambda: {"summary": {"missing_keys": 0, "raw_keys_visible": 0, "mixed_language_strings": 0}},
    )
    monkeypatch.setattr(
        admin_mod,
        "admin_founder_daily",
        lambda admin_actor, db: {
            "focus": "Quality",
            "north_star": {"metric": "active_chats", "value": 42},
            "today_plan": [{"title": "Ship", "reason": "r", "action": "a"}],
            "alerts": [],
        },
    )
    monkeypatch.setattr(
        admin_mod,
        "ai_quality",
        lambda admin_actor, db: {"summary": {"selection_rate": 0.55, "edited_rate": 0.12}},
    )
    monkeypatch.setattr(admin_mod, "admin_autopilot_suggestions", lambda admin_actor, db: {"suggestions": []})
    monkeypatch.setattr(admin_mod, "admin_product_manager_daily_brief", lambda period, admin_actor, db: {"health_score": 85})
    monkeypatch.setattr(admin_mod, "admin_cto_roadmap", lambda period, admin_actor, db: {"technical_health_score": 88})
    monkeypatch.setattr(
        admin_mod,
        "admin_command_center_home",
        lambda admin_actor, db: {
            "status": "healthy",
            "headline": "Systems healthy",
            "today": {
                "active_users": 40,
                "new_users": 8,
                "matches": 4,
                "messages": 20,
                "ai_calls": 6,
                "premium_users": 2,
                "open_reports": 0,
            },
            "critical_alerts": [],
            "top_recommendation": {"title": "Ship", "reason": "Momentum", "action": "Keep quality high"},
        },
    )
    monkeypatch.setattr(
        admin_mod,
        "system_doctor",
        lambda admin_actor, db: {
            "api_status": "ok",
            "api_errors_24h": 0,
            "uptime_seconds": 7200,
            "environment": "test",
            "database_status": "ok",
            "redis_status": "ok",
            "alembic_revision": "test_rev",
            "users_count": 100,
            "matches_count": 20,
            "profiles_count": 100,
            "messages_count": 200,
            "gemini_status": "ok",
            "last_gemini_error": None,
            "ai_fallback_count_24h": 0,
            "gemini_model": "gemini-test",
        },
    )
    monkeypatch.setattr(admin_mod, "admin_alerts_poll", lambda admin_actor, db: {"alerts": []})

    def _stats_safe(period, admin_actor, db):
        return {
            "period": period,
            "users": {
                "total": 200,
                "new": 12,
                "active": 55,
                "completed_profiles_rate": 0.82,
                "verified_profiles_rate": 0.15,
            },
            "dating": {"likes": 40, "matches": 10, "messages": 120, "active_chats": 8, "dead_chats": 1},
            "ai": {
                "ai_calls": 25,
                "fallback_count": 1,
                "gemini_errors": 0,
                "reply_selected_rate": 0.55,
                "partner_reply_after_ai_rate": 0.48,
            },
            "premium": {"trial_users": 2, "premium_users": 4, "expired_trials": 1, "conversion_rate": 0.12},
            "safety": {"open_reports": 0, "new_reports": 0, "banned_users": 0},
        }

    monkeypatch.setattr(admin_mod, "admin_stats_overview", _stats_safe)
    monkeypatch.setattr(
        admin_mod,
        "admin_premium_overview",
        lambda admin_actor, db: {
            "trial_users": 1,
            "premium_users": 3,
            "expired_trials": 0,
            "expiring_trials_24h": 0,
            "expiring_trials_3d": 1,
            "conversion_rate": 0.1,
            "premium_revenue_best_effort": 0,
            "top_paywall_sources": [],
        },
    )
    monkeypatch.setattr(
        admin_mod, "admin_audit_log", lambda limit, offset, action_type, admin_actor, db: {"total": 3, "items": []}
    )
    monkeypatch.setattr(admin_mod, "admin_e2e_qa_scan", _e2e_ok)
    monkeypatch.setattr(admin_mod, "admin_telegram_menu_qa_scan", _menu_ok)
    monkeypatch.setattr(
        admin_mod,
        "admin_backups_list",
        lambda *a, **k: [{"filename": "b.sqlite", "created_at": "2026-04-26T15:00:00+00:00", "size_bytes": 1, "type": "sqlite", "environment": "test"}],
    )
    monkeypatch.setattr(admin_mod, "_release_backup_recent", lambda hours=24: (True, "ok"))

    def _rel(*a, **k):
        return {
            "ready": True,
            "score": 90,
            "environment": "development",
            "checks": [],
            "blockers": [],
            "warnings": [],
            "recommended_actions": [],
        }

    monkeypatch.setattr(admin_mod, "admin_release_readiness", _rel)
    res = _client().get("/api/v1/admin/system/full-analysis")
    assert res.status_code == 200
    assert int(res.json().get("score") or 0) >= 95


def test_full_analysis_includes_create_backup_quick_action(monkeypatch):
    monkeypatch.setattr(admin_mod, "admin_backups_list", lambda *a, **k: [])
    res = _client().get("/api/v1/admin/system/full-analysis")
    assert res.status_code == 200
    j = res.json()
    qa = j.get("quick_actions") or []
    assert any(x.get("callback_data") == "c:backup_create" for x in qa)
    assert any((x.get("title") or "").lower().find("backup") >= 0 for x in qa)


def test_full_analysis_backup_recent_is_healthy(monkeypatch):
    monkeypatch.setattr(
        admin_mod,
        "admin_backups_list",
        lambda *a, **k: [{"filename": "neyra_backup_test.sqlite", "created_at": "2026-04-26T15:00:00+00:00", "size_bytes": 1, "type": "sqlite", "environment": "test"}],
    )
    monkeypatch.setattr(admin_mod, "_release_backup_recent", lambda hours=24: (True, "Latest backup fresh"))

    def _rel(*a, **k):
        return {
            "ready": True,
            "score": 88,
            "environment": "development",
            "checks": [],
            "blockers": [],
            "warnings": [],
            "recommended_actions": [],
        }

    monkeypatch.setattr(admin_mod, "admin_release_readiness", _rel)
    res = _client().get("/api/v1/admin/system/full-analysis")
    assert res.status_code == 200
    sec = next((s for s in res.json()["sections"] if s.get("id") == "backups_audit_release"), {})
    assert sec.get("status") == "healthy"
    assert "last 24h: yes" in (sec.get("summary") or "").lower()


def test_full_analysis_telegram_section_not_critical_for_unsafe_heuristic_only(monkeypatch):
    def _menu_qa(admin_actor):
        return {
            "status": "warning",
            "summary": {
                "menus_checked": 2,
                "buttons_checked": 2,
                "callbacks_checked": 2,
                "missing_handlers": 0,
                "missing_translations": 0,
                "unsafe_actions": 4,
                "render_errors": 0,
            },
        }

    monkeypatch.setattr(admin_mod, "admin_telegram_menu_qa_scan", _menu_qa)
    res = _client().get("/api/v1/admin/system/full-analysis")
    assert res.status_code == 200
    sec = next((s for s in res.json()["sections"] if s.get("id") == "telegram_menu"), {})
    assert sec.get("status") == "warning"
    assert not any(str(x).lower().startswith("menu qa: ") and "missing handler" in str(x).lower() for x in (sec.get("issues") or []))


def test_full_analysis_survives_partial_subsystem_failure(monkeypatch):
    orig = admin_mod.admin_stats_overview

    def _wrap(period, admin_actor, db):
        if period == "30d":
            raise RuntimeError("simulated_30d_failure")
        return orig(period, admin_actor, db)

    monkeypatch.setattr(admin_mod, "admin_stats_overview", _wrap)
    client = _client()
    res = client.get("/api/v1/admin/system/full-analysis")
    assert res.status_code == 200
    j = res.json()
    assert j["status"] in {"healthy", "warning", "critical"}
    # Copy is intentionally non-stable; assert the summary reflects a partial run.
    assert "skipped" in j["owner_summary"].lower()


def test_full_analysis_optional_partial_does_not_flag_core_load_failure(monkeypatch):
    orig = admin_mod.admin_stats_overview

    def _wrap(period, admin_actor, db):
        if period == "30d":
            raise RuntimeError("simulated_30d_failure")
        return orig(period, admin_actor, db)

    monkeypatch.setattr(admin_mod, "admin_stats_overview", _wrap)
    res = _client().get("/api/v1/admin/system/full-analysis")
    assert res.status_code == 200
    sec = next((s for s in res.json()["sections"] if s.get("id") == "system"), {})
    # Optional subfeeds failing should not be reported as "core load failure".
    assert not any("core diagnostics could not be loaded" in str(x).lower() for x in (sec.get("issues") or []))


def test_telegram_main_menu_full_analysis_is_last_row():
    import types
    from importlib.machinery import SourceFileLoader
    from importlib.util import module_from_spec, spec_from_loader
    from pathlib import Path
    import sys

    script = Path(__file__).resolve().parents[1] / "scripts" / "telegram_admin_bot.py"
    loader = SourceFileLoader("telegram_admin_bot_fa_menu", str(script))
    spec = spec_from_loader("telegram_admin_bot_fa_menu", loader)
    assert spec is not None
    bot = module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["telegram_admin_bot_fa_menu"] = bot
    spec.loader.exec_module(bot)  # type: ignore[attr-defined]

    bot.admin_lang[42] = "en"
    rows = bot.main_menu(42)
    assert rows[-1][0]["callback_data"] == "m:full_analysis"
    assert "Full System Analysis" in rows[-1][0]["text"]
    bot.admin_lang[42] = "uk"
    rows_uk = bot.main_menu(42)
    assert "Повний аналіз" in rows_uk[-1][0]["text"]


def test_telegram_full_analysis_routing_calls_backend(monkeypatch):
    import types
    from importlib.machinery import SourceFileLoader
    from importlib.util import module_from_spec, spec_from_loader
    from pathlib import Path
    import sys

    script = Path(__file__).resolve().parents[1] / "scripts" / "telegram_admin_bot.py"
    loader = SourceFileLoader("telegram_admin_bot_fa_route", str(script))
    spec = spec_from_loader("telegram_admin_bot_fa_route", loader)
    assert spec is not None
    bot = module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["telegram_admin_bot_fa_route"] = bot
    spec.loader.exec_module(bot)  # type: ignore[attr-defined]

    monkeypatch.setattr(bot, "ADMIN_TELEGRAM_IDS", {7})
    bot.admin_lang[7] = "en"

    called = {"path": None}

    def _req(method, path, json_body=None):
        called["path"] = path
        return {
            "status": "healthy",
            "score": 91,
            "generated_at": "2026-04-26T00:00:00+00:00",
            "sections": [{"id": "system", "title": "System / Runtime", "status": "healthy", "summary": "OK", "details": [], "issues": [], "recommended_actions": []}],
            "top_issues": [],
            "top_recommendations": [],
            "next_best_actions": [],
            "owner_summary": "All clear.",
        }

    monkeypatch.setattr(bot, "backend", types.SimpleNamespace(request=_req))
    monkeypatch.setattr(bot, "tg_edit", lambda *a, **k: None)
    monkeypatch.setattr(bot, "tg_answer_callback", lambda *a, **k: None)

    bot.route_callback("m:full_analysis", chat_id=1, msg_id=2, user_id=7, cbq_id="cbq")
    assert called["path"] == "/api/v1/admin/system/full-analysis"
