import types
from importlib.machinery import SourceFileLoader
from importlib.util import spec_from_loader
from pathlib import Path
import sys


def _load_bot_module(name: str):
    script = Path(__file__).resolve().parents[1] / "scripts" / "telegram_admin_bot.py"
    loader = SourceFileLoader(name, str(script))
    spec = spec_from_loader(name, loader)
    bot = types.ModuleType(name)
    sys.modules[name] = bot
    assert spec and spec.loader
    spec.loader.exec_module(bot)  # type: ignore[attr-defined]
    return bot


def test_strings_uk_en_key_parity():
    bot = _load_bot_module("telegram_admin_bot_i18n_parity")
    assert set(bot.STRINGS["uk"].keys()) == set(bot.STRINGS["en"].keys())


def test_telegram_demo_strings_uk_en_non_empty():
    bot = _load_bot_module("telegram_admin_bot_demo_i18n")
    en = bot.STRINGS["en"]
    uk = bot.STRINGS["uk"]
    demo_keys = [k for k in en if k.startswith("telegram.demo.")]
    assert demo_keys
    for k in demo_keys:
        assert uk.get(k), f"missing or empty uk: {k}"
        assert en.get(k), f"missing or empty en: {k}"
        assert str(uk[k]).strip() != str(k), f"uk raw key leaked: {k}"


def test_telegram_route_strings_uk_en_parity():
    bot = _load_bot_module("telegram_admin_bot_route_i18n")
    en = bot.STRINGS["en"]
    uk = bot.STRINGS["uk"]
    route_keys = [k for k in en if k.startswith("telegram.route.")]
    assert route_keys
    for k in route_keys:
        assert k in uk and str(uk[k]).strip(), f"missing uk: {k}"
        assert str(en[k]).strip(), f"missing en: {k}"


def test_t_function_falls_back_to_en_for_missing_uk_key(monkeypatch):
    bot = _load_bot_module("telegram_admin_bot_t_fallback")
    monkeypatch.setattr(bot, "admin_lang", {999001: "uk"})
    monkeypatch.setenv("ENV", "development")
    # Synthetic missing key: not in uk, present in en
    bot.STRINGS["en"]["__test_fallback_only"] = "English fallback"
    out = bot.t(999001, "__test_fallback_only")
    assert out == "English fallback"


def test_backend_session_sends_service_token_header(monkeypatch):
    bot = _load_bot_module("telegram_admin_bot_service_token_test")

    called = {}

    def _fake_request(method, url, headers=None, json=None, timeout=None):
        called["method"] = method
        called["url"] = url
        called["headers"] = dict(headers or {})

        class _Resp:
            status_code = 200

            def raise_for_status(self):
                return None

            def json(self):
                return {"ok": True}

        return _Resp()

    monkeypatch.setattr(bot, "BACKEND_BASE_URL", "http://example")
    monkeypatch.setattr(bot.requests, "request", _fake_request)

    s = bot.BackendSession(service_token="svc-token-123")
    out = s.request("GET", "/api/v1/admin/system-doctor")
    assert out == {"ok": True}
    assert called["headers"]["X-Admin-Service-Token"] == "svc-token-123"


def _command_center_payload() -> dict:
    return {
        "status": "healthy",
        "headline": "Healthy. Focus on growth and conversation quality.",
        "today": {
            "new_users": 2,
            "active_users": 8,
            "matches": 3,
            "messages": 12,
            "ai_calls": 5,
            "premium_users": 1,
            "open_reports": 0,
        },
        "critical_alerts": [],
        "top_recommendation": {
            "title": "Improve AI replies",
            "reason": "High edit rate",
            "action": "Tune prompts",
        },
        "quick_actions": [{"id": "system_doctor", "label": "System Doctor", "risk": "none"}],
    }


def _alerts_payload() -> dict:
    return {
        "alerts": [
            {
                "id": "gemini_errors_high",
                "level": "critical",
                "title": "Gemini errors are rising",
                "message": "Recent Gemini provider errors were detected.",
                "source": "ai",
                "created_at": "2026-04-26T00:00:00+00:00",
                "dedupe_key": "ai:gemini_errors_high",
                "action": {"label": "Open System Doctor", "callback": "m:system"},
            }
        ]
    }


def _backups_payload() -> list[dict]:
    return [
        {
            "filename": "neyra_backup_20260426_120000.sqlite",
            "created_at": "2026-04-26T12:00:00+00:00",
            "size_bytes": 12,
            "type": "sqlite",
            "environment": "development",
        }
    ]


def _audit_payload() -> dict:
    return {
        "items": [
            {
                "id": 1,
                "created_at": "2026-04-26T12:00:00+00:00",
                "admin_user_id": 999,
                "action": "grant_premium",
                "target_type": "premium",
                "target_id": "123",
                "status": "success",
                "metadata": {"days": 7},
            }
        ],
        "total": 1,
    }


def _release_payload() -> dict:
    return {
        "ready": True,
        "score": 86,
        "environment": "development",
        "checks": [
            {
                "id": "tests",
                "title": "Backend tests",
                "status": "pass",
                "details": "165 tests passed",
                "blocking": True,
            }
        ],
        "blockers": [],
        "warnings": ["Redis healthy"],
        "recommended_actions": ["Create a fresh backup before release."],
    }


def _patch_command_center_backend(monkeypatch, bot) -> list[tuple[str, str, dict | None]]:
    calls: list[tuple[str, str, dict | None]] = []

    def _backend_request(method, path, json_body=None):
        calls.append((method, path, json_body))
        if path == "/api/v1/admin/command-center/home":
            return _command_center_payload()
        return {}

    monkeypatch.setattr(bot, "backend", types.SimpleNamespace(request=_backend_request))
    return calls


def _patch_alerts_backend(monkeypatch, bot) -> list[tuple[str, str, dict | None]]:
    calls: list[tuple[str, str, dict | None]] = []

    def _backend_request(method, path, json_body=None):
        calls.append((method, path, json_body))
        if path == "/api/v1/admin/alerts/poll":
            return _alerts_payload()
        if path == "/api/v1/admin/command-center/home":
            return _command_center_payload()
        return {}

    monkeypatch.setattr(bot, "backend", types.SimpleNamespace(request=_backend_request))
    return calls


def _patch_backups_backend(monkeypatch, bot) -> list[tuple[str, str, dict | None]]:
    calls: list[tuple[str, str, dict | None]] = []

    class _Backend:
        def request(self, method, path, json_body=None):
            calls.append((method, path, json_body))
            if path == "/api/v1/admin/backups":
                return _backups_payload()
            if path == "/api/v1/admin/backups/create":
                return {
                    "success": True,
                    "filename": "neyra_backup_new.sqlite",
                    "size": 10,
                    "size_bytes": 10,
                    "duration_seconds": 0.012,
                    "created_at": "2026-04-26T12:01:00+00:00",
                }
            if path.endswith("/restore"):
                return {"ok": True, "restored": True, "filename": "neyra_backup_20260426_120000.sqlite"}
            if path == "/api/v1/admin/command-center/home":
                return _command_center_payload()
            return {}

        def download(self, path):
            calls.append(("DOWNLOAD", path, None))
            return "neyra_backup_20260426_120000.sqlite", b"backup"

    monkeypatch.setattr(bot, "backend", _Backend())
    return calls


def _patch_audit_backend(monkeypatch, bot) -> list[tuple[str, str, dict | None]]:
    calls: list[tuple[str, str, dict | None]] = []

    def _backend_request(method, path, json_body=None):
        calls.append((method, path, json_body))
        if path.startswith("/api/v1/admin/audit-log"):
            return _audit_payload()
        if path == "/api/v1/admin/command-center/home":
            return _command_center_payload()
        return {}

    monkeypatch.setattr(bot, "backend", types.SimpleNamespace(request=_backend_request))
    return calls


def _patch_release_backend(monkeypatch, bot) -> list[tuple[str, str, dict | None]]:
    calls: list[tuple[str, str, dict | None]] = []

    def _backend_request(method, path, json_body=None):
        calls.append((method, path, json_body))
        if path == "/api/v1/admin/release/readiness":
            return _release_payload()
        if path == "/api/v1/admin/release/mark":
            return {"ok": True, "version": json_body.get("version"), "environment": "development", "marked_at": "2026-04-26T00:00:00+00:00"}
        if path == "/api/v1/admin/command-center/home":
            return _command_center_payload()
        return {}

    monkeypatch.setattr(bot, "backend", types.SimpleNamespace(request=_backend_request))
    return calls


def test_callback_routing_handles_unknown_action_without_crash(monkeypatch):
    from importlib.machinery import SourceFileLoader
    from importlib.util import module_from_spec, spec_from_loader
    from pathlib import Path
    import sys

    script = Path(__file__).resolve().parents[1] / "scripts" / "telegram_admin_bot.py"
    loader = SourceFileLoader("telegram_admin_bot", str(script))
    spec = spec_from_loader("telegram_admin_bot", loader)
    assert spec is not None
    bot = module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["telegram_admin_bot"] = bot
    spec.loader.exec_module(bot)  # type: ignore

    # Make admin
    monkeypatch.setattr(bot, "ADMIN_TELEGRAM_IDS", {123})

    # Stub telegram methods
    called = {"edit": 0, "answer": 0}

    def _edit(chat_id, msg_id, text, keyboard=None):
        called["edit"] += 1

    def _answer(cbq_id, text=""):
        called["answer"] += 1

    monkeypatch.setattr(bot, "tg_edit", _edit)
    monkeypatch.setattr(bot, "tg_answer_callback", _answer)

    # Unknown action should just answer callback.
    bot.route_callback("x:unknown", chat_id=1, msg_id=2, user_id=123, cbq_id="cbq")
    assert called["answer"] == 1


def test_callback_routing_system_doctor_confirm_flow(monkeypatch):
    import types
    from importlib.machinery import SourceFileLoader
    from importlib.util import module_from_spec, spec_from_loader
    from pathlib import Path
    import sys

    script = Path(__file__).resolve().parents[1] / "scripts" / "telegram_admin_bot.py"
    loader = SourceFileLoader("telegram_admin_bot2", str(script))
    spec = spec_from_loader("telegram_admin_bot2", loader)
    assert spec is not None
    bot = module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["telegram_admin_bot2"] = bot
    spec.loader.exec_module(bot)  # type: ignore

    monkeypatch.setattr(bot, "ADMIN_TELEGRAM_IDS", {123})

    # Stub backend request + telegram side effects
    def _backend_request(method, path, json_body=None):
        if path.endswith("/system-doctor"):
            return {"api_status": "ok", "database_status": "ok", "redis_status": "disabled", "gemini_status": "disabled", "api_errors_24h": 0, "ai_fallback_count_24h": 0, "environment": "test", "uptime_seconds": 1, "alembic_revision": None, "last_10_errors": []}
        if path.endswith("/system/clear-cache"):
            return {"ok": True}
        return {}

    monkeypatch.setattr(bot, "backend", types.SimpleNamespace(request=_backend_request))

    called = {"edit": 0, "answer": 0}
    monkeypatch.setattr(bot, "tg_edit", lambda *a, **k: called.__setitem__("edit", called["edit"] + 1))
    monkeypatch.setattr(bot, "tg_answer_callback", lambda *a, **k: called.__setitem__("answer", called["answer"] + 1))

    bot.route_callback("c:clear_cache", chat_id=1, msg_id=2, user_id=123, cbq_id="cbq")
    assert called["edit"] >= 1


def test_callback_routing_users_open_details(monkeypatch):
    from importlib.machinery import SourceFileLoader
    from importlib.util import module_from_spec, spec_from_loader
    from pathlib import Path
    import sys
    import types

    script = Path(__file__).resolve().parents[1] / "scripts" / "telegram_admin_bot.py"
    loader = SourceFileLoader("telegram_admin_bot_users", str(script))
    spec = spec_from_loader("telegram_admin_bot_users", loader)
    assert spec is not None
    bot = module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["telegram_admin_bot_users"] = bot
    spec.loader.exec_module(bot)  # type: ignore

    monkeypatch.setattr(bot, "ADMIN_TELEGRAM_IDS", {123})

    def _backend_request(method, path, json_body=None):
        if path.endswith("/users/1"):
            return {"user": {"id": 1, "is_banned": False}, "profile": {"display_name": "Alice"}, "photos_count": 0, "matches_count": 0, "messages_count": 0, "reports_count": 0, "ai_memory_exists": False, "subscription": None}
        return []

    monkeypatch.setattr(bot, "backend", types.SimpleNamespace(request=_backend_request))

    called = {"edit": 0}
    monkeypatch.setattr(bot, "tg_edit", lambda *a, **k: called.__setitem__("edit", called["edit"] + 1))
    monkeypatch.setattr(bot, "tg_answer_callback", lambda *a, **k: None)

    bot.route_callback("u:1", chat_id=1, msg_id=2, user_id=123, cbq_id="cbq")
    assert called["edit"] == 1


def test_callback_routing_reports_open_list(monkeypatch):
    from importlib.machinery import SourceFileLoader
    from importlib.util import module_from_spec, spec_from_loader
    from pathlib import Path
    import sys
    import types

    script = Path(__file__).resolve().parents[1] / "scripts" / "telegram_admin_bot.py"
    loader = SourceFileLoader("telegram_admin_bot_reports", str(script))
    spec = spec_from_loader("telegram_admin_bot_reports", loader)
    assert spec is not None
    bot = module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["telegram_admin_bot_reports"] = bot
    spec.loader.exec_module(bot)  # type: ignore

    monkeypatch.setattr(bot, "ADMIN_TELEGRAM_IDS", {123})

    def _backend_request(method, path, json_body=None):
        if path.startswith("/api/v1/admin/reports?status=open"):
            return [{"report_id": 1, "reported_user_id": 2, "category": "spam", "reason": "spam", "status": "open"}]
        return {}

    monkeypatch.setattr(bot, "backend", types.SimpleNamespace(request=_backend_request))
    monkeypatch.setattr(bot, "tg_answer_callback", lambda *a, **k: None)
    called = {"edit": 0}
    monkeypatch.setattr(bot, "tg_edit", lambda *a, **k: called.__setitem__("edit", called["edit"] + 1))

    bot.route_callback("m:reports_open", chat_id=1, msg_id=2, user_id=123, cbq_id="cbq")
    assert called["edit"] == 1


def test_callback_routing_stats_today(monkeypatch):
    from importlib.machinery import SourceFileLoader
    from importlib.util import module_from_spec, spec_from_loader
    from pathlib import Path
    import sys
    import types

    script = Path(__file__).resolve().parents[1] / "scripts" / "telegram_admin_bot.py"
    loader = SourceFileLoader("telegram_admin_bot_stats", str(script))
    spec = spec_from_loader("telegram_admin_bot_stats", loader)
    assert spec is not None
    bot = module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["telegram_admin_bot_stats"] = bot
    spec.loader.exec_module(bot)  # type: ignore

    monkeypatch.setattr(bot, "ADMIN_TELEGRAM_IDS", {123})

    def _backend_request(method, path, json_body=None):
        if path.startswith("/api/v1/admin/stats/overview?period=today"):
            return {
                "period": "today",
                "users": {"total": 1, "new": 1, "active": 1, "completed_profiles_rate": 1.0, "verified_profiles_rate": 1.0},
                "dating": {"likes": 0, "matches": 0, "messages": 0, "active_chats": 0, "dead_chats": 0},
                "ai": {"ai_calls": 0, "fallback_count": 0, "gemini_errors": 0, "reply_selected_rate": 0.0, "partner_reply_after_ai_rate": 0.0},
                "premium": {"trial_users": 0, "premium_users": 0, "expired_trials": 0, "conversion_rate": 0.0},
                "safety": {"open_reports": 0, "new_reports": 0, "banned_users": 0},
            }
        return {}

    monkeypatch.setattr(bot, "backend", types.SimpleNamespace(request=_backend_request))
    monkeypatch.setattr(bot, "tg_answer_callback", lambda *a, **k: None)
    called = {"edit": 0}
    monkeypatch.setattr(bot, "tg_edit", lambda *a, **k: called.__setitem__("edit", called["edit"] + 1))

    bot.route_callback("m:stats_today", chat_id=1, msg_id=2, user_id=123, cbq_id="cbq")
    assert called["edit"] == 1


def test_callback_routing_premium_overview(monkeypatch):
    from importlib.machinery import SourceFileLoader
    from importlib.util import module_from_spec, spec_from_loader
    from pathlib import Path
    import sys
    import types

    script = Path(__file__).resolve().parents[1] / "scripts" / "telegram_admin_bot.py"
    loader = SourceFileLoader("telegram_admin_bot_premium", str(script))
    spec = spec_from_loader("telegram_admin_bot_premium", loader)
    assert spec is not None
    bot = module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["telegram_admin_bot_premium"] = bot
    spec.loader.exec_module(bot)  # type: ignore

    monkeypatch.setattr(bot, "ADMIN_TELEGRAM_IDS", {123})

    def _backend_request(method, path, json_body=None):
        if path == "/api/v1/admin/premium/overview":
            return {"trial_users": 0, "premium_users": 0, "expired_trials": 0, "expiring_trials_24h": 0, "expiring_trials_3d": 0, "conversion_rate": 0.0, "premium_revenue_best_effort": 0, "top_paywall_sources": []}
        return {}

    monkeypatch.setattr(bot, "backend", types.SimpleNamespace(request=_backend_request))
    monkeypatch.setattr(bot, "tg_answer_callback", lambda *a, **k: None)
    called = {"edit": 0}
    monkeypatch.setattr(bot, "tg_edit", lambda *a, **k: called.__setitem__("edit", called["edit"] + 1))

    bot.route_callback("m:premium_overview", chat_id=1, msg_id=2, user_id=123, cbq_id="cbq")
    assert called["edit"] == 1


def test_callback_routing_match_quality_overview(monkeypatch):
    from importlib.machinery import SourceFileLoader
    from importlib.util import module_from_spec, spec_from_loader
    from pathlib import Path
    import sys
    import types

    script = Path(__file__).resolve().parents[1] / "scripts" / "telegram_admin_bot.py"
    loader = SourceFileLoader("telegram_admin_bot_mq", str(script))
    spec = spec_from_loader("telegram_admin_bot_mq", loader)
    assert spec is not None
    bot = module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["telegram_admin_bot_mq"] = bot
    spec.loader.exec_module(bot)  # type: ignore

    monkeypatch.setattr(bot, "ADMIN_TELEGRAM_IDS", {123})

    def _backend_request(method, path, json_body=None):
        if path == "/api/v1/admin/match-quality/overview":
            return {
                "total_matches": 0,
                "matches_today": 0,
                "mutual_like_rate": 0.0,
                "average_compatibility_score": 0.0,
                "weak_matches_count": 0,
                "dead_chats_count": 0,
                "active_chats_count": 0,
                "reply_rate": 0.0,
                "ai_match_coverage_rate": 0.0,
                "top_match_issues": [],
            }
        return {}

    monkeypatch.setattr(bot, "backend", types.SimpleNamespace(request=_backend_request))
    monkeypatch.setattr(bot, "tg_answer_callback", lambda *a, **k: None)
    called = {"edit": 0}
    monkeypatch.setattr(bot, "tg_edit", lambda *a, **k: called.__setitem__("edit", called["edit"] + 1))

    bot.route_callback("m:match_quality_overview", chat_id=1, msg_id=2, user_id=123, cbq_id="cbq")
    assert called["edit"] == 1


def test_callback_routing_match_quality_recompute_shows_confirm(monkeypatch):
    from importlib.machinery import SourceFileLoader
    from importlib.util import module_from_spec, spec_from_loader
    from pathlib import Path
    import sys
    import types

    script = Path(__file__).resolve().parents[1] / "scripts" / "telegram_admin_bot.py"
    loader = SourceFileLoader("telegram_admin_bot_mq_recompute", str(script))
    spec = spec_from_loader("telegram_admin_bot_mq_recompute", loader)
    assert spec is not None
    bot = module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["telegram_admin_bot_mq_recompute"] = bot
    spec.loader.exec_module(bot)  # type: ignore

    monkeypatch.setattr(bot, "ADMIN_TELEGRAM_IDS", {123})
    monkeypatch.setattr(bot, "backend", types.SimpleNamespace(request=lambda *a, **k: {}))
    monkeypatch.setattr(bot, "tg_answer_callback", lambda *a, **k: None)
    last: dict = {}

    def _tg_edit(cid, mid, text, kb=None):
        last["text"] = text
        last["kb"] = kb

    monkeypatch.setattr(bot, "tg_edit", _tg_edit)

    bot.route_callback("m:match_quality_recompute", chat_id=1, msg_id=2, user_id=123, cbq_id="cbq")
    kb = last.get("kb") or []
    assert kb and any(
        any((btn or {}).get("callback_data") == "x:match_quality_recompute_yes" for btn in (row or [])) for row in kb
    )
    assert "confirm" in (last.get("text") or "").lower() or "підтвердження" in (last.get("text") or "").lower()

    def _post_ok(method, path, json_body=None):
        assert method == "POST" and path == "/api/v1/admin/match-quality/recompute"
        assert (json_body or {}).get("confirm") is True
        return {"ok": True, "processed": 1, "failed": 0}

    monkeypatch.setattr(bot, "backend", types.SimpleNamespace(request=_post_ok))
    bot.route_callback("x:match_quality_recompute_yes", chat_id=1, msg_id=2, user_id=123, cbq_id="cbq2")
    assert "processed" in (last.get("text") or "").lower() or "1" in (last.get("text") or "")


def test_language_selector_start_flow_and_switch(monkeypatch):
    from importlib.machinery import SourceFileLoader
    from importlib.util import module_from_spec, spec_from_loader
    from pathlib import Path
    import sys

    script = Path(__file__).resolve().parents[1] / "scripts" / "telegram_admin_bot.py"
    loader = SourceFileLoader("telegram_admin_bot_lang", str(script))
    spec = spec_from_loader("telegram_admin_bot_lang", loader)
    assert spec is not None
    bot = module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["telegram_admin_bot_lang"] = bot
    spec.loader.exec_module(bot)  # type: ignore

    monkeypatch.setattr(bot, "ADMIN_TELEGRAM_IDS", {123})
    monkeypatch.setattr(bot, "tg_answer_callback", lambda *a, **k: None)
    sent = {"text": "", "kb": None}

    def _tg_send(chat_id, text, keyboard=None):
        sent["text"] = text
        sent["kb"] = keyboard

    monkeypatch.setattr(bot, "tg_send", _tg_send)
    monkeypatch.setattr(bot, "tg_edit", lambda *a, **k: None)
    calls = _patch_command_center_backend(monkeypatch, bot)

    # /start should ask for language if not selected
    bot.route_message("/start", chat_id=1, user_id=123)
    assert "Choose" in sent["text"] or "Оберіть" in sent["text"]
    assert sent["kb"] is not None

    # Switch to Ukrainian
    bot.route_callback("x:lang:uk", chat_id=1, msg_id=2, user_id=123, cbq_id="cbq")
    # Now /menu should open the Command Center home
    bot.route_message("/menu", chat_id=1, user_id=123)
    assert "NEYRA Command Center" in sent["text"]
    assert "Improve AI replies" in sent["text"]

    # Switch to English and ensure home remains the Command Center
    bot.route_callback("x:lang:en", chat_id=1, msg_id=2, user_id=123, cbq_id="cbq")
    bot.route_message("/menu", chat_id=1, user_id=123)
    assert "NEYRA Command Center" in sent["text"]
    assert ("GET", "/api/v1/admin/command-center/home", None) in calls


def test_start_routes_to_command_center_home_after_language_selected(monkeypatch):
    from importlib.machinery import SourceFileLoader
    from importlib.util import module_from_spec, spec_from_loader
    from pathlib import Path
    import sys

    script = Path(__file__).resolve().parents[1] / "scripts" / "telegram_admin_bot.py"
    loader = SourceFileLoader("telegram_admin_bot_command_center_start", str(script))
    spec = spec_from_loader("telegram_admin_bot_command_center_start", loader)
    assert spec is not None
    bot = module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["telegram_admin_bot_command_center_start"] = bot
    spec.loader.exec_module(bot)  # type: ignore

    monkeypatch.setattr(bot, "ADMIN_TELEGRAM_IDS", {123})
    monkeypatch.setattr(bot, "admin_lang", {123: "en"})
    _patch_command_center_backend(monkeypatch, bot)
    sent = {"text": "", "kb": None}
    monkeypatch.setattr(bot, "tg_send", lambda chat_id, text, keyboard=None: sent.update({"text": text, "kb": keyboard}))

    bot.route_message("/start", chat_id=1, user_id=123)
    assert "NEYRA Command Center" in sent["text"]
    assert "Status:" in sent["text"]
    assert any(btn.get("callback_data") == "m:more" for row in sent["kb"] for btn in row)


def test_callback_routing_command_center_home_and_more_menu(monkeypatch):
    from importlib.machinery import SourceFileLoader
    from importlib.util import module_from_spec, spec_from_loader
    from pathlib import Path
    import sys

    script = Path(__file__).resolve().parents[1] / "scripts" / "telegram_admin_bot.py"
    loader = SourceFileLoader("telegram_admin_bot_command_center_more", str(script))
    spec = spec_from_loader("telegram_admin_bot_command_center_more", loader)
    assert spec is not None
    bot = module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["telegram_admin_bot_command_center_more"] = bot
    spec.loader.exec_module(bot)  # type: ignore

    monkeypatch.setattr(bot, "ADMIN_TELEGRAM_IDS", {123})
    monkeypatch.setattr(bot, "admin_lang", {123: "en"})
    _patch_command_center_backend(monkeypatch, bot)
    monkeypatch.setattr(bot, "tg_answer_callback", lambda *a, **k: None)
    edits: list[tuple[str, list[list[dict[str, str]]] | None]] = []
    monkeypatch.setattr(bot, "tg_edit", lambda chat_id, msg_id, text, keyboard=None: edits.append((text, keyboard)))

    bot.route_callback("m:home", chat_id=1, msg_id=2, user_id=123, cbq_id="cbq")
    bot.route_callback("m:more", chat_id=1, msg_id=2, user_id=123, cbq_id="cbq")

    assert "NEYRA Command Center" in edits[0][0]
    assert any(btn.get("callback_data") == "m:ai" for row in edits[0][1] for btn in row)
    assert any(btn.get("callback_data") == "m:more" for row in edits[0][1] for btn in row)
    assert "Choose a section" in edits[1][0]
    assert any(btn.get("callback_data") == "m:demo" for row in edits[1][1] for btn in row)
    assert any(btn.get("callback_data") == "m:pm" for row in edits[1][1] for btn in row)
    assert any(btn.get("callback_data") == "m:autopilot" for row in edits[1][1] for btn in row)


def test_callback_routing_alerts_active_and_mute_unmute(monkeypatch):
    from importlib.machinery import SourceFileLoader
    from importlib.util import module_from_spec, spec_from_loader
    from pathlib import Path
    import sys

    script = Path(__file__).resolve().parents[1] / "scripts" / "telegram_admin_bot.py"
    loader = SourceFileLoader("telegram_admin_bot_alerts_menu", str(script))
    spec = spec_from_loader("telegram_admin_bot_alerts_menu", loader)
    assert spec is not None
    bot = module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["telegram_admin_bot_alerts_menu"] = bot
    spec.loader.exec_module(bot)  # type: ignore

    monkeypatch.setattr(bot, "ADMIN_TELEGRAM_IDS", {123})
    monkeypatch.setattr(bot, "admin_lang", {123: "en"})
    _patch_alerts_backend(monkeypatch, bot)
    monkeypatch.setattr(bot, "tg_answer_callback", lambda *a, **k: None)
    edits: list[tuple[str, list[list[dict[str, str]]] | None]] = []
    monkeypatch.setattr(bot, "tg_edit", lambda chat_id, msg_id, text, keyboard=None: edits.append((text, keyboard)))

    bot.route_callback("m:alerts", chat_id=1, msg_id=2, user_id=123, cbq_id="cbq")
    bot.route_callback("m:alerts_active", chat_id=1, msg_id=2, user_id=123, cbq_id="cbq")
    bot.route_callback("x:alerts_mute_1h", chat_id=1, msg_id=2, user_id=123, cbq_id="cbq")
    assert bot.alerts_muted_until > 0
    bot.route_callback("x:alerts_unmute", chat_id=1, msg_id=2, user_id=123, cbq_id="cbq")
    assert bot.alerts_muted_until == 0.0

    assert "Alerts" in edits[0][0]
    assert "Gemini errors are rising" in edits[1][0]
    assert any(btn.get("callback_data") == "m:system" for row in edits[1][1] for btn in row)


def test_alert_polling_dedupes_notifications(monkeypatch):
    from importlib.machinery import SourceFileLoader
    from importlib.util import module_from_spec, spec_from_loader
    from pathlib import Path
    import sys

    script = Path(__file__).resolve().parents[1] / "scripts" / "telegram_admin_bot.py"
    loader = SourceFileLoader("telegram_admin_bot_alerts_poll", str(script))
    spec = spec_from_loader("telegram_admin_bot_alerts_poll", loader)
    assert spec is not None
    bot = module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["telegram_admin_bot_alerts_poll"] = bot
    spec.loader.exec_module(bot)  # type: ignore

    monkeypatch.setattr(bot, "ADMIN_TELEGRAM_IDS", {123})
    _patch_alerts_backend(monkeypatch, bot)
    sent: list[tuple[int, str, list[list[dict[str, str]]] | None]] = []
    monkeypatch.setattr(bot, "tg_send", lambda chat_id, text, keyboard=None: sent.append((chat_id, text, keyboard)))

    first = bot.poll_alerts_once(force=True)
    second = bot.poll_alerts_once(force=True)

    assert len(first) == 1
    assert second == []
    assert len(sent) == 1
    assert "NEYRA Alert" in sent[0][1]
    assert sent[0][2][0][0]["callback_data"] == "m:system"


def test_callback_routing_backup_center_create_list_export_restore(monkeypatch):
    from importlib.machinery import SourceFileLoader
    from importlib.util import module_from_spec, spec_from_loader
    from pathlib import Path
    import sys

    script = Path(__file__).resolve().parents[1] / "scripts" / "telegram_admin_bot.py"
    loader = SourceFileLoader("telegram_admin_bot_backup_center", str(script))
    spec = spec_from_loader("telegram_admin_bot_backup_center", loader)
    assert spec is not None
    bot = module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["telegram_admin_bot_backup_center"] = bot
    spec.loader.exec_module(bot)  # type: ignore

    monkeypatch.setattr(bot, "ADMIN_TELEGRAM_IDS", {123})
    monkeypatch.setattr(bot, "admin_lang", {123: "en"})
    calls = _patch_backups_backend(monkeypatch, bot)
    monkeypatch.setattr(bot, "tg_answer_callback", lambda *a, **k: None)
    edits: list[tuple[str, list[list[dict[str, str]]] | None]] = []
    sent: list[tuple[str, list[list[dict[str, str]]] | None]] = []
    docs: list[tuple[str, bytes, str]] = []

    def _tg_send_captured(chat_id, text, keyboard=None):
        sent.append((text, keyboard))
        return 777

    monkeypatch.setattr(bot, "tg_edit", lambda chat_id, msg_id, text, keyboard=None: edits.append((text, keyboard)))
    monkeypatch.setattr(bot, "tg_send", _tg_send_captured)
    monkeypatch.setattr(bot, "tg_send_document", lambda chat_id, filename, content, caption="": docs.append((filename, content, caption)))

    bot.route_callback("m:backups", chat_id=1, msg_id=2, user_id=123, cbq_id="cbq")
    bot.route_callback("m:backups_list", chat_id=1, msg_id=2, user_id=123, cbq_id="cbq")
    bot.route_callback("c:backup_create", chat_id=1, msg_id=2, user_id=123, cbq_id="cbq")
    bot.route_callback("x:backup_create_yes", chat_id=1, msg_id=2, user_id=123, cbq_id="cbq")
    bot.route_callback("x:backup_export_latest", chat_id=1, msg_id=2, user_id=123, cbq_id="cbq")
    bot.route_callback("m:backups_restore", chat_id=1, msg_id=2, user_id=123, cbq_id="cbq")
    bot.route_callback("c:backup_restore:neyra_backup_20260426_120000.sqlite", chat_id=1, msg_id=2, user_id=123, cbq_id="cbq")
    bot.route_message("RESTORE NEYRA BACKUP", chat_id=1, user_id=123)
    bot.route_callback("x:backup_restore:neyra_backup_20260426_120000.sqlite", chat_id=1, msg_id=2, user_id=123, cbq_id="cbq")

    assert "Backup Center" in edits[0][0]
    assert "neyra_backup_20260426_120000.sqlite" in edits[1][0]
    assert docs and docs[0][0] == "neyra_backup_20260426_120000.sqlite"
    assert any("Typed phrase accepted" in text for text, _kb in sent)
    assert ("POST", "/api/v1/admin/backups/create", {"confirm": True}) in calls
    assert (
        "POST",
        "/api/v1/admin/backups/neyra_backup_20260426_120000.sqlite/restore",
        {"confirm": True, "confirm_phrase": "RESTORE NEYRA BACKUP"},
    ) in calls
    assert any("Creating backup" in (t or "") for t, _kb in sent), "loading message should be sent immediately"
    assert any("Backup created" in (e[0] or "") for e in edits), "success status should be shown"
    assert any("neyra_backup_new.sqlite" in (e[0] or "") for e in edits)
    assert any("10 B" in (e[0] or "") or "KB" in (e[0] or "") for e in edits)
    assert any("Duration" in (e[0] or "") for e in edits)


def test_backup_create_shows_error_when_api_payload_missing_success(monkeypatch):
    from importlib.machinery import SourceFileLoader
    from importlib.util import module_from_spec, spec_from_loader
    from pathlib import Path
    import sys

    script = Path(__file__).resolve().parents[1] / "scripts" / "telegram_admin_bot.py"
    loader = SourceFileLoader("telegram_admin_bot_backup_bad_payload", str(script))
    spec = spec_from_loader("telegram_admin_bot_backup_bad_payload", loader)
    assert spec is not None
    bot = module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["telegram_admin_bot_backup_bad_payload"] = bot
    spec.loader.exec_module(bot)  # type: ignore

    monkeypatch.setattr(bot, "ADMIN_TELEGRAM_IDS", {123})
    monkeypatch.setattr(bot, "admin_lang", {123: "en"})

    class _B:
        def request(self, method, path, json_body=None):
            if path == "/api/v1/admin/backups":
                return _backups_payload()
            if path == "/api/v1/admin/backups/create":
                return {"filename": "only_name.sqlite", "size_bytes": 1}
            return {}

        def download(self, path):
            return "x.sqlite", b"x"

    monkeypatch.setattr(bot, "backend", _B())
    monkeypatch.setattr(bot, "tg_answer_callback", lambda *a, **k: None)
    edits: list[tuple[str, list[list[dict[str, str]]] | None]] = []
    sent: list[tuple[str, list[list[dict[str, str]]] | None]] = []

    def _tg_send_captured(chat_id, text, keyboard=None):
        sent.append((text, keyboard))
        return 777

    monkeypatch.setattr(bot, "tg_edit", lambda chat_id, msg_id, text, keyboard=None: edits.append((text, keyboard)))
    monkeypatch.setattr(bot, "tg_send", _tg_send_captured)

    bot.route_callback("c:backup_create", chat_id=1, msg_id=2, user_id=123, cbq_id="cbq")
    bot.route_callback("x:backup_create_yes", chat_id=1, msg_id=2, user_id=123, cbq_id="cbq2")

    assert any("Creating backup" in (t or "") for t, _kb in sent)
    assert any("Backup failed" in (e[0] or "") and "Invalid or empty" in (e[0] or "") for e in edits)


def test_backup_create_sends_error_status_on_failure(monkeypatch):
    from importlib.machinery import SourceFileLoader
    from importlib.util import module_from_spec, spec_from_loader
    from pathlib import Path
    import sys

    script = Path(__file__).resolve().parents[1] / "scripts" / "telegram_admin_bot.py"
    loader = SourceFileLoader("telegram_admin_bot_backup_fail", str(script))
    spec = spec_from_loader("telegram_admin_bot_backup_fail", loader)
    assert spec is not None
    bot = module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["telegram_admin_bot_backup_fail"] = bot
    spec.loader.exec_module(bot)  # type: ignore

    monkeypatch.setattr(bot, "ADMIN_TELEGRAM_IDS", {123})
    monkeypatch.setattr(bot, "admin_lang", {123: "en"})

    class _B:
        def request(self, method, path, json_body=None):
            if path == "/api/v1/admin/backups":
                return _backups_payload()
            if path == "/api/v1/admin/backups/create":
                raise RuntimeError("simulated_backup_failure")
            return {}

        def download(self, path):
            return "x.sqlite", b"x"

    monkeypatch.setattr(bot, "backend", _B())
    monkeypatch.setattr(bot, "tg_answer_callback", lambda *a, **k: None)
    edits: list[tuple[str, list[list[dict[str, str]]] | None]] = []
    sent: list[tuple[str, list[list[dict[str, str]]] | None]] = []

    def _tg_send_captured(chat_id, text, keyboard=None):
        sent.append((text, keyboard))
        return 888

    monkeypatch.setattr(bot, "tg_edit", lambda chat_id, msg_id, text, keyboard=None: edits.append((text, keyboard)))
    monkeypatch.setattr(bot, "tg_send", _tg_send_captured)

    bot.route_callback("c:backup_create", chat_id=1, msg_id=2, user_id=123, cbq_id="cbq")
    bot.route_callback("x:backup_create_yes", chat_id=1, msg_id=2, user_id=123, cbq_id="cbq2")

    assert any("Creating backup" in (t or "") for t, _kb in sent)
    assert any("Backup failed" in (e[0] or "") for e in edits)
    assert any("simulated_backup_failure" in (e[0] or "") for e in edits)
    assert any("Duration" in (e[0] or "") for e in edits)


def test_callback_routing_audit_log_views(monkeypatch):
    from importlib.machinery import SourceFileLoader
    from importlib.util import module_from_spec, spec_from_loader
    from pathlib import Path
    import sys

    script = Path(__file__).resolve().parents[1] / "scripts" / "telegram_admin_bot.py"
    loader = SourceFileLoader("telegram_admin_bot_audit_log", str(script))
    spec = spec_from_loader("telegram_admin_bot_audit_log", loader)
    assert spec is not None
    bot = module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["telegram_admin_bot_audit_log"] = bot
    spec.loader.exec_module(bot)  # type: ignore

    monkeypatch.setattr(bot, "ADMIN_TELEGRAM_IDS", {123})
    monkeypatch.setattr(bot, "admin_lang", {123: "en"})
    calls = _patch_audit_backend(monkeypatch, bot)
    monkeypatch.setattr(bot, "tg_answer_callback", lambda *a, **k: None)
    edits: list[tuple[str, list[list[dict[str, str]]] | None]] = []
    monkeypatch.setattr(bot, "tg_edit", lambda chat_id, msg_id, text, keyboard=None: edits.append((text, keyboard)))

    bot.route_callback("m:audit", chat_id=1, msg_id=2, user_id=123, cbq_id="cbq")
    bot.route_callback("m:audit_last", chat_id=1, msg_id=2, user_id=123, cbq_id="cbq")
    bot.route_callback("m:audit_premium", chat_id=1, msg_id=2, user_id=123, cbq_id="cbq")

    assert "Audit Log" in edits[0][0]
    assert "grant_premium" in edits[1][0]
    assert "premium:123" in edits[1][0]
    assert any("/api/v1/admin/audit-log?limit=20&offset=0" == call[1] for call in calls)
    assert any("action_type=premium" in call[1] for call in calls)


def test_callback_routing_release_manager_readiness_and_mark(monkeypatch):
    from importlib.machinery import SourceFileLoader
    from importlib.util import module_from_spec, spec_from_loader
    from pathlib import Path
    import sys

    script = Path(__file__).resolve().parents[1] / "scripts" / "telegram_admin_bot.py"
    loader = SourceFileLoader("telegram_admin_bot_release_manager", str(script))
    spec = spec_from_loader("telegram_admin_bot_release_manager", loader)
    assert spec is not None
    bot = module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["telegram_admin_bot_release_manager"] = bot
    spec.loader.exec_module(bot)  # type: ignore

    monkeypatch.setattr(bot, "ADMIN_TELEGRAM_IDS", {123})
    monkeypatch.setattr(bot, "admin_lang", {123: "en"})
    calls = _patch_release_backend(monkeypatch, bot)
    monkeypatch.setattr(bot, "tg_answer_callback", lambda *a, **k: None)
    edits: list[tuple[str, list[list[dict[str, str]]] | None]] = []
    sent: list[tuple[str, list[list[dict[str, str]]] | None]] = []
    monkeypatch.setattr(bot, "tg_edit", lambda chat_id, msg_id, text, keyboard=None: edits.append((text, keyboard)))
    monkeypatch.setattr(bot, "tg_send", lambda chat_id, text, keyboard=None: sent.append((text, keyboard)))

    bot.route_callback("m:release", chat_id=1, msg_id=2, user_id=123, cbq_id="cbq")
    bot.route_callback("m:release_readiness", chat_id=1, msg_id=2, user_id=123, cbq_id="cbq")
    bot.route_callback("m:release_blockers", chat_id=1, msg_id=2, user_id=123, cbq_id="cbq")
    bot.route_callback("c:release_mark", chat_id=1, msg_id=2, user_id=123, cbq_id="cbq")
    bot.route_message("0.1.0 | Initial beta", chat_id=1, user_id=123)
    bot.route_callback("x:release_mark_yes", chat_id=1, msg_id=2, user_id=123, cbq_id="cbq")

    assert "Release Manager" in edits[0][0]
    assert "Score: 86/100" in edits[1][0]
    assert "Blockers" in edits[2][0]
    assert any("Version:" in text for text, _kb in sent)
    assert ("POST", "/api/v1/admin/release/mark", {"version": "0.1.0", "notes": "Initial beta", "confirm": True}) in calls


def test_callback_routing_conversation_quality_today(monkeypatch):
    from importlib.machinery import SourceFileLoader
    from importlib.util import module_from_spec, spec_from_loader
    from pathlib import Path
    import sys
    import types

    script = Path(__file__).resolve().parents[1] / "scripts" / "telegram_admin_bot.py"
    loader = SourceFileLoader("telegram_admin_bot_cq", str(script))
    spec = spec_from_loader("telegram_admin_bot_cq", loader)
    assert spec is not None
    bot = module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["telegram_admin_bot_cq"] = bot
    spec.loader.exec_module(bot)  # type: ignore

    monkeypatch.setattr(bot, "ADMIN_TELEGRAM_IDS", {123})
    monkeypatch.setattr(bot, "admin_lang", {123: "en"})

    def _backend_request(method, path, json_body=None):
        if path.startswith("/api/v1/admin/conversation-quality/overview"):
            return {
                "period": "today",
                "summary": {
                    "ai_options_shown": 0,
                    "ai_options_selected": 0,
                    "selection_rate": 0.0,
                    "edited_rate": 0.0,
                    "message_sent_after_ai": 0,
                    "partner_reply_after_ai": 0,
                    "partner_reply_rate": 0.0,
                    "duplicate_rate": 0.0,
                    "stall_detected_count": 0,
                    "revive_used_count": 0,
                    "meeting_suggested_count": 0,
                    "meeting_rejected_count": 0,
                },
                "styles": {"light": {"reply_rate": 0.0}, "flirty": {"reply_rate": 0.0}, "deep": {"reply_rate": 0.0}},
                "issues": [],
            }
        return {}

    monkeypatch.setattr(bot, "backend", types.SimpleNamespace(request=_backend_request))
    monkeypatch.setattr(bot, "tg_answer_callback", lambda *a, **k: None)
    called = {"edit": 0}
    monkeypatch.setattr(bot, "tg_edit", lambda *a, **k: called.__setitem__("edit", called["edit"] + 1))

    bot.route_callback("m:conversation_quality_today", chat_id=1, msg_id=2, user_id=123, cbq_id="cbq")
    assert called["edit"] == 1


def test_callback_routing_growth_7d(monkeypatch):
    from importlib.machinery import SourceFileLoader
    from importlib.util import module_from_spec, spec_from_loader
    from pathlib import Path
    import sys
    import types

    script = Path(__file__).resolve().parents[1] / "scripts" / "telegram_admin_bot.py"
    loader = SourceFileLoader("telegram_admin_bot_growth", str(script))
    spec = spec_from_loader("telegram_admin_bot_growth", loader)
    assert spec is not None
    bot = module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["telegram_admin_bot_growth"] = bot
    spec.loader.exec_module(bot)  # type: ignore

    monkeypatch.setattr(bot, "ADMIN_TELEGRAM_IDS", {123})
    monkeypatch.setattr(bot, "admin_lang", {123: "en"})

    def _backend_request(method, path, json_body=None):
        if path.startswith("/api/v1/admin/growth/overview"):
            return {
                "period": "7d",
                "acquisition": {"new_users": 0, "signups_by_locale": {}, "signups_by_country": {}, "top_sources": {}},
                "activation": {"profile_completed_rate": 0.0, "photo_added_rate": 0.0, "first_like_rate": 0.0, "first_match_rate": 0.0, "first_message_rate": 0.0},
                "retention": {"active_users": 0, "returning_users": 0, "day_1_retention_best_effort": 0.0, "dead_users_count": 0},
                "monetization": {"premium_users": 0, "trial_users": 0, "paywall_views": 0, "premium_conversion_rate": 0.0, "top_paywall_sources": {}},
                "recommendations": [],
            }
        return {}

    monkeypatch.setattr(bot, "backend", types.SimpleNamespace(request=_backend_request))
    monkeypatch.setattr(bot, "tg_answer_callback", lambda *a, **k: None)
    called = {"edit": 0}
    monkeypatch.setattr(bot, "tg_edit", lambda *a, **k: called.__setitem__("edit", called["edit"] + 1))

    bot.route_callback("m:growth_7d", chat_id=1, msg_id=2, user_id=123, cbq_id="cbq")
    assert called["edit"] == 1


def test_callback_routing_product_manager_daily(monkeypatch):
    from importlib.machinery import SourceFileLoader
    from importlib.util import module_from_spec, spec_from_loader
    from pathlib import Path
    import sys
    import types

    script = Path(__file__).resolve().parents[1] / "scripts" / "telegram_admin_bot.py"
    loader = SourceFileLoader("telegram_admin_bot_pm", str(script))
    spec = spec_from_loader("telegram_admin_bot_pm", loader)
    assert spec is not None
    bot = module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["telegram_admin_bot_pm"] = bot
    spec.loader.exec_module(bot)  # type: ignore

    monkeypatch.setattr(bot, "ADMIN_TELEGRAM_IDS", {123})
    monkeypatch.setattr(bot, "admin_lang", {123: "en"})

    def _backend_request(method, path, json_body=None):
        if path.startswith("/api/v1/admin/product-manager/daily-brief"):
            return {
                "period": "today",
                "health_score": 80,
                "top_priority": {"title": "Test", "reason": "Because", "impact": "high", "effort": "low", "recommended_action": "Do X"},
                "priorities": [],
                "wins": [],
                "risks": [],
                "next_actions": [],
            }
        return {}

    monkeypatch.setattr(bot, "backend", types.SimpleNamespace(request=_backend_request))
    monkeypatch.setattr(bot, "tg_answer_callback", lambda *a, **k: None)
    called = {"edit": 0}
    monkeypatch.setattr(bot, "tg_edit", lambda *a, **k: called.__setitem__("edit", called["edit"] + 1))

    bot.route_callback("m:pm_today", chat_id=1, msg_id=2, user_id=123, cbq_id="cbq")
    assert called["edit"] == 1


def test_bilingual_menu_label_product_manager(monkeypatch):
    from importlib.machinery import SourceFileLoader
    from importlib.util import module_from_spec, spec_from_loader
    from pathlib import Path
    import sys

    script = Path(__file__).resolve().parents[1] / "scripts" / "telegram_admin_bot.py"
    loader = SourceFileLoader("telegram_admin_bot_pm_lbl", str(script))
    spec = spec_from_loader("telegram_admin_bot_pm_lbl", loader)
    assert spec is not None
    bot = module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["telegram_admin_bot_pm_lbl"] = bot
    spec.loader.exec_module(bot)  # type: ignore

    # Ensure key exists in both languages.
    assert "product_manager" in bot.STRINGS["en"]
    assert "product_manager" in bot.STRINGS["uk"]


def test_callback_routing_cto_today(monkeypatch):
    from importlib.machinery import SourceFileLoader
    from importlib.util import module_from_spec, spec_from_loader
    from pathlib import Path
    import sys
    import types

    script = Path(__file__).resolve().parents[1] / "scripts" / "telegram_admin_bot.py"
    loader = SourceFileLoader("telegram_admin_bot_cto", str(script))
    spec = spec_from_loader("telegram_admin_bot_cto", loader)
    assert spec is not None
    bot = module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["telegram_admin_bot_cto"] = bot
    spec.loader.exec_module(bot)  # type: ignore

    monkeypatch.setattr(bot, "ADMIN_TELEGRAM_IDS", {123})
    monkeypatch.setattr(bot, "admin_lang", {123: "en"})

    def _backend_request(method, path, json_body=None):
        if path.startswith("/api/v1/admin/cto/roadmap"):
            return {
                "period": "today",
                "technical_health_score": 75,
                "top_engineering_priority": {"title": "Stability", "reason": "Errors", "impact": "high", "risk": "high", "recommended_action": "Fix top errors"},
                "priorities": [],
                "technical_debt": [],
                "risks": [],
                "next_actions": [],
            }
        return {}

    monkeypatch.setattr(bot, "backend", types.SimpleNamespace(request=_backend_request))
    monkeypatch.setattr(bot, "tg_answer_callback", lambda *a, **k: None)
    called = {"edit": 0}
    monkeypatch.setattr(bot, "tg_edit", lambda *a, **k: called.__setitem__("edit", called["edit"] + 1))

    bot.route_callback("m:cto_today", chat_id=1, msg_id=2, user_id=123, cbq_id="cbq")
    assert called["edit"] == 1


def test_bilingual_menu_label_cto_exists(monkeypatch):
    from importlib.machinery import SourceFileLoader
    from importlib.util import module_from_spec, spec_from_loader
    from pathlib import Path
    import sys

    script = Path(__file__).resolve().parents[1] / "scripts" / "telegram_admin_bot.py"
    loader = SourceFileLoader("telegram_admin_bot_cto_lbl", str(script))
    spec = spec_from_loader("telegram_admin_bot_cto_lbl", loader)
    assert spec is not None
    bot = module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["telegram_admin_bot_cto_lbl"] = bot
    spec.loader.exec_module(bot)  # type: ignore

    assert "cto" in bot.STRINGS["en"]
    assert "cto" in bot.STRINGS["uk"]


def test_callback_routing_menu_qa_run(monkeypatch):
    from importlib.machinery import SourceFileLoader
    from importlib.util import module_from_spec, spec_from_loader
    from pathlib import Path
    import sys
    import types

    script = Path(__file__).resolve().parents[1] / "scripts" / "telegram_admin_bot.py"
    loader = SourceFileLoader("telegram_admin_bot_menuqa", str(script))
    spec = spec_from_loader("telegram_admin_bot_menuqa", loader)
    assert spec is not None
    bot = module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["telegram_admin_bot_menuqa"] = bot
    spec.loader.exec_module(bot)  # type: ignore

    monkeypatch.setattr(bot, "ADMIN_TELEGRAM_IDS", {123})
    monkeypatch.setattr(bot, "admin_lang", {123: "en"})

    def _backend_request(method, path, json_body=None):
        if path == "/api/v1/admin/telegram-menu-qa/scan":
            return {"status": "pass", "summary": {"menus_checked": 1, "buttons_checked": 1, "callbacks_checked": 1, "missing_handlers": 0, "missing_translations": 0, "unsafe_actions": 0, "render_errors": 0}, "issues": []}
        return {}

    monkeypatch.setattr(bot, "backend", types.SimpleNamespace(request=_backend_request))
    monkeypatch.setattr(bot, "tg_answer_callback", lambda *a, **k: None)
    called = {"edit": 0}
    monkeypatch.setattr(bot, "tg_edit", lambda *a, **k: called.__setitem__("edit", called["edit"] + 1))

    bot.route_callback("m:menu_qa_run", chat_id=1, msg_id=2, user_id=123, cbq_id="cbq")
    assert called["edit"] == 1


def test_callback_routing_e2e_qa_run(monkeypatch):
    from importlib.machinery import SourceFileLoader
    from importlib.util import module_from_spec, spec_from_loader
    from pathlib import Path
    import sys
    import types

    script = Path(__file__).resolve().parents[1] / "scripts" / "telegram_admin_bot.py"
    loader = SourceFileLoader("telegram_admin_bot_e2eqa", str(script))
    spec = spec_from_loader("telegram_admin_bot_e2eqa", loader)
    assert spec is not None
    bot = module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["telegram_admin_bot_e2eqa"] = bot
    spec.loader.exec_module(bot)  # type: ignore

    monkeypatch.setattr(bot, "ADMIN_TELEGRAM_IDS", {123})
    monkeypatch.setattr(bot, "admin_lang", {123: "en"})

    def _backend_request(method, path, json_body=None):
        if path == "/api/v1/admin/e2e-qa/scan":
            return {
                "status": "warning",
                "summary": {"flows_checked": 1, "passed": 0, "warnings": 1, "failed": 0},
                "flows": [{"id": "chat_ai", "title": "AI chat copilot", "status": "warning", "steps_checked": 1, "issues": []}],
                "issues": [],
            }
        return {}

    monkeypatch.setattr(bot, "backend", types.SimpleNamespace(request=_backend_request))
    monkeypatch.setattr(bot, "tg_answer_callback", lambda *a, **k: None)
    called = {"edit": 0}
    monkeypatch.setattr(bot, "tg_edit", lambda *a, **k: called.__setitem__("edit", called["edit"] + 1))

    bot.route_callback("m:e2e_qa_run", chat_id=1, msg_id=2, user_id=123, cbq_id="cbq")
    assert called["edit"] == 1


def test_ai_help_button_in_major_menus_and_callback_handler(monkeypatch):
    from importlib.machinery import SourceFileLoader
    from importlib.util import module_from_spec, spec_from_loader
    from pathlib import Path
    import sys
    import types

    script = Path(__file__).resolve().parents[1] / "scripts" / "telegram_admin_bot.py"
    loader = SourceFileLoader("telegram_admin_bot_aihelp", str(script))
    spec = spec_from_loader("telegram_admin_bot_aihelp", loader)
    assert spec is not None
    bot = module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["telegram_admin_bot_aihelp"] = bot
    spec.loader.exec_module(bot)  # type: ignore

    monkeypatch.setattr(bot, "ADMIN_TELEGRAM_IDS", {123})
    monkeypatch.setattr(bot, "admin_lang", {123: "en"})

    def _backend_request(method, path, json_body=None):
        if path == "/api/v1/admin/ai-help" and method.upper() == "POST":
            return {
                "section": "premium",
                "title": "💎 Premium",
                "explanation": "x",
                "issues": [],
                "suggestions": ["y"],
            }
        if path.startswith("/api/v1/admin/ai-help/"):
            return {
                "section": "premium",
                "title": "💎 Premium",
                "summary": "x",
                "what_to_watch": [],
                "recommended_actions": [],
                "risk_notes": [],
                "next_best_action": "y",
            }
        return {}

    monkeypatch.setattr(bot, "backend", types.SimpleNamespace(request=_backend_request))
    monkeypatch.setattr(bot, "tg_answer_callback", lambda *a, **k: None)

    captured = {"kb": None, "text": ""}

    def _tg_edit(chat_id, msg_id, text, keyboard=None):
        captured["kb"] = keyboard
        captured["text"] = text

    monkeypatch.setattr(bot, "tg_edit", _tg_edit)

    # Major menus (m: keys) that must inject AI Help
    major = [
        "m:home",
        "m:stats",
        "m:users",
        "m:safety",
        "m:premium",
        "m:match_quality",
        "m:conversation_quality",
        "m:growth",
        "m:pm",
        "m:cto",
        "m:autopilot",
        "m:founder",
        "m:alerts",
        "m:system",
        "m:backups",
        "m:audit",
        "m:release",
        "m:menu_qa",
        "m:e2e_qa",
        "m:l10n",
        "m:l10n_agent",
        "m:l10n_coverage",
    ]
    for cb in major:
        bot.route_callback(cb, chat_id=1, msg_id=2, user_id=123, cbq_id="cbq")
        kb = captured["kb"]
        # AI Help button should be present
        flat = []
        for row in kb or []:
            for b in row or []:
                if isinstance(b, dict):
                    flat.append(b.get("callback_data"))
        assert any(str(x).startswith("ai_help:") for x in flat)

    # And ai_help callback must be handled without crash
    bot.route_callback("ai_help:premium", chat_id=1, msg_id=2, user_id=123, cbq_id="cbq")
    assert "AI Analysis" in captured["text"] or "AI Help" in captured["text"]

    # Submenus should also inject AI Help
    bot.route_callback("m:premium_overview", chat_id=1, msg_id=2, user_id=123, cbq_id="cbq")
    kb_sub = captured["kb"]
    flat_sub = []
    for row in kb_sub or []:
        for b in row or []:
            if isinstance(b, dict):
                flat_sub.append(b.get("callback_data"))
    assert any(str(x).startswith("ai_help:premium~") for x in flat_sub)


def test_localization_coverage_telegram_callbacks(monkeypatch):
    import types

    bot = _load_bot_module("telegram_admin_bot_lcov")

    monkeypatch.setattr(bot, "ADMIN_TELEGRAM_IDS", {123})
    monkeypatch.setattr(bot, "admin_lang", {123: "en"})

    calls = []

    def _req(method: str, path: str, json_body=None):
        calls.append((method, path))
        if path.endswith("/localization/coverage"):
            return {
                "generated_at": "2026-01-01T00:00:00+00:00",
                "locales": [
                    {
                        "code": "en",
                        "coverage": 100,
                        "total_keys": 3,
                        "translated_keys": 3,
                        "missing": 0,
                        "identical_to_en": 0,
                        "empty": 0,
                        "top_missing_keys": [],
                        "top_identical_to_en_keys": [],
                    },
                    {
                        "code": "ja",
                        "coverage": 33,
                        "total_keys": 3,
                        "translated_keys": 1,
                        "missing": 1,
                        "identical_to_en": 1,
                        "empty": 0,
                        "top_missing_keys": ["x.y"],
                        "top_identical_to_en_keys": ["a.b"],
                    },
                ],
            }
        return {}

    monkeypatch.setattr(bot, "backend", types.SimpleNamespace(request=_req))
    monkeypatch.setattr(bot, "tg_answer_callback", lambda *a, **k: None)
    captured = {}

    def _edit(_c, _m, text, keyboard=None):
        captured["text"] = text

    monkeypatch.setattr(bot, "tg_edit", _edit)

    bot.route_callback("m:l10n_coverage", chat_id=1, msg_id=2, user_id=123, cbq_id="cbq")
    assert any("/localization/coverage" in p for _, p in calls)
    assert "JA" in captured.get("text", "") or "ja" in captured.get("text", "").lower()

    bot.route_callback("x:l10n_cov_miss", chat_id=1, msg_id=2, user_id=123, cbq_id="cbq")
    assert "missing" in captured.get("text", "").lower()

    bot.route_callback("x:l10n_cov_fix", chat_id=1, msg_id=2, user_id=123, cbq_id="cbq")
    assert "identical" in captured.get("text", "").lower() or "english" in captured.get("text", "").lower()


def test_localization_agent_telegram_callbacks(monkeypatch):
    import types

    bot = _load_bot_module("telegram_admin_bot_lagent")

    monkeypatch.setattr(bot, "ADMIN_TELEGRAM_IDS", {123})
    monkeypatch.setattr(bot, "admin_lang", {123: "en"})

    calls: list[tuple[str, str, dict | None]] = []

    def _req(method: str, path: str, json_body=None):
        calls.append((method, path, json_body))
        if path.endswith("/localization-agent/scan"):
            return {
                "status": "pass",
                "summary": {
                    "missing_keys": 0,
                    "raw_keys_visible": 0,
                    "mixed_language_strings": 0,
                    "bad_city_cases": 0,
                    "unsupported_locales": 0,
                },
                "issues": [],
            }
        if path.endswith("/localization-agent/fix"):
            return {"ok": True, "report_path": "reports/x.json", "scan_before": {}, "scan_after": {}, "diff_summary": {}}
        return {}

    monkeypatch.setattr(bot, "backend", types.SimpleNamespace(request=_req))
    monkeypatch.setattr(bot, "tg_answer_callback", lambda *a, **k: None)

    captured: dict[str, str] = {}

    def _edit(_cid, _mid, text, keyboard=None):
        captured["text"] = text

    monkeypatch.setattr(bot, "tg_edit", _edit)

    bot.route_callback("x:lagent_scan", chat_id=1, msg_id=2, user_id=123, cbq_id="cbq")
    assert calls and calls[0][0] == "GET" and "/localization-agent/scan" in calls[0][1]
    assert "Scan" in captured.get("text", "")

    bot.route_callback("x:lagent_missing", chat_id=1, msg_id=2, user_id=123, cbq_id="cbq")
    assert "Missing keys" in captured.get("text", "")

    bot.route_callback("x:lagent_cities", chat_id=1, msg_id=2, user_id=123, cbq_id="cbq")
    assert "Bad city cases" in captured.get("text", "")

    bot.set_confirm(1, 123, "lagent_fix", {})
    bot.route_callback("x:lagent_fix_yes", chat_id=1, msg_id=2, user_id=123, cbq_id="cbq")
    assert any(c[0] == "POST" and "/localization-agent/fix" in c[1] for c in calls)
    fix_body = next(c[2] for c in calls if c[0] == "POST" and "/localization-agent/fix" in c[1])
    assert fix_body == {"confirm": True, "mode": "safe"}


def test_bilingual_menu_label_autopilot_exists(monkeypatch):
    from importlib.machinery import SourceFileLoader
    from importlib.util import module_from_spec, spec_from_loader
    from pathlib import Path
    import sys

    script = Path(__file__).resolve().parents[1] / "scripts" / "telegram_admin_bot.py"
    loader = SourceFileLoader("telegram_admin_bot_autopilot_lbl", str(script))
    spec = spec_from_loader("telegram_admin_bot_autopilot_lbl", loader)
    assert spec is not None
    bot = module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["telegram_admin_bot_autopilot_lbl"] = bot
    spec.loader.exec_module(bot)  # type: ignore

    assert bot.STRINGS["en"]["autopilot"] == "🤖 Autopilot"
    assert bot.STRINGS["uk"]["autopilot"] == "🤖 Автопілот"
    assert "autopilot_suggestions" in bot.STRINGS["en"]
    assert "autopilot_run_action" in bot.STRINGS["uk"]


def test_bilingual_menu_label_founder_exists(monkeypatch):
    from importlib.machinery import SourceFileLoader
    from importlib.util import module_from_spec, spec_from_loader
    from pathlib import Path
    import sys

    script = Path(__file__).resolve().parents[1] / "scripts" / "telegram_admin_bot.py"
    loader = SourceFileLoader("telegram_admin_bot_founder_lbl", str(script))
    spec = spec_from_loader("telegram_admin_bot_founder_lbl", loader)
    assert spec is not None
    bot = module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["telegram_admin_bot_founder_lbl"] = bot
    spec.loader.exec_module(bot)  # type: ignore

    assert bot.STRINGS["en"]["founder"] == "👑 Founder Mode"
    assert bot.STRINGS["uk"]["founder"] == "👑 Режим засновника"
    assert bot.STRINGS["en"]["founder_daily_plan"] == "Daily plan"
    assert bot.STRINGS["uk"]["founder_alerts"] == "Алерти"


def test_callback_routing_founder_daily(monkeypatch):
    from importlib.machinery import SourceFileLoader
    from importlib.util import module_from_spec, spec_from_loader
    from pathlib import Path
    import sys
    import types

    script = Path(__file__).resolve().parents[1] / "scripts" / "telegram_admin_bot.py"
    loader = SourceFileLoader("telegram_admin_bot_founder_daily", str(script))
    spec = spec_from_loader("telegram_admin_bot_founder_daily", loader)
    assert spec is not None
    bot = module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["telegram_admin_bot_founder_daily"] = bot
    spec.loader.exec_module(bot)  # type: ignore

    monkeypatch.setattr(bot, "ADMIN_TELEGRAM_IDS", {123})
    monkeypatch.setattr(bot, "admin_lang", {123: "en"})

    def _backend_request(method, path, json_body=None):
        if path == "/api/v1/admin/founder/daily":
            return {
                "date": "2026-04-26",
                "north_star": {"metric": "Daily active conversations", "value": 124, "trend": "up"},
                "today_plan": [
                    {
                        "priority": 1,
                        "title": "Improve AI replies",
                        "reason": "High edit rate",
                        "expected_impact": "high",
                        "action": "Tune prompts",
                    }
                ],
                "alerts": [{"level": "warning", "message": "Gemini errors rising", "suggested_fix": "Check provider"}],
                "wins": [],
                "focus": "Improve conversation quality",
            }
        return {}

    monkeypatch.setattr(bot, "backend", types.SimpleNamespace(request=_backend_request))
    monkeypatch.setattr(bot, "tg_answer_callback", lambda *a, **k: None)
    edited = {"text": "", "kb": None}
    monkeypatch.setattr(bot, "tg_edit", lambda chat_id, msg_id, text, keyboard=None: edited.update({"text": text, "kb": keyboard}))

    bot.route_callback("m:founder_daily", chat_id=1, msg_id=2, user_id=123, cbq_id="cbq")
    assert "Founder Mode" in edited["text"]
    assert "North Star" in edited["text"]
    assert "Improve AI replies" in edited["text"]
    assert "Gemini errors rising" in edited["text"]
    assert any(btn.get("callback_data") == "m:founder_alerts" for row in edited["kb"] for btn in row)


def test_callback_routing_founder_alerts_and_focus(monkeypatch):
    from importlib.machinery import SourceFileLoader
    from importlib.util import module_from_spec, spec_from_loader
    from pathlib import Path
    import sys
    import types

    script = Path(__file__).resolve().parents[1] / "scripts" / "telegram_admin_bot.py"
    loader = SourceFileLoader("telegram_admin_bot_founder_views", str(script))
    spec = spec_from_loader("telegram_admin_bot_founder_views", loader)
    assert spec is not None
    bot = module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["telegram_admin_bot_founder_views"] = bot
    spec.loader.exec_module(bot)  # type: ignore

    monkeypatch.setattr(bot, "ADMIN_TELEGRAM_IDS", {123})
    monkeypatch.setattr(bot, "admin_lang", {123: "en"})

    def _backend_request(method, path, json_body=None):
        if path == "/api/v1/admin/founder/daily":
            return {
                "date": "2026-04-26",
                "north_star": {"metric": "Daily active conversations", "value": 1, "trend": "flat"},
                "today_plan": [],
                "alerts": [{"level": "critical", "message": "Database health is not OK", "suggested_fix": "Review migrations"}],
                "wins": [],
                "focus": "Stabilize core systems",
            }
        return {}

    monkeypatch.setattr(bot, "backend", types.SimpleNamespace(request=_backend_request))
    monkeypatch.setattr(bot, "tg_answer_callback", lambda *a, **k: None)
    edited = {"texts": []}
    monkeypatch.setattr(bot, "tg_edit", lambda chat_id, msg_id, text, keyboard=None: edited["texts"].append(text))

    bot.route_callback("m:founder_alerts", chat_id=1, msg_id=2, user_id=123, cbq_id="cbq")
    bot.route_callback("m:founder_focus", chat_id=1, msg_id=2, user_id=123, cbq_id="cbq")
    assert any("Database health is not OK" in text for text in edited["texts"])
    assert any("Stabilize core systems" in text for text in edited["texts"])


def test_callback_routing_autopilot_suggestions(monkeypatch):
    from importlib.machinery import SourceFileLoader
    from importlib.util import module_from_spec, spec_from_loader
    from pathlib import Path
    import sys
    import types

    script = Path(__file__).resolve().parents[1] / "scripts" / "telegram_admin_bot.py"
    loader = SourceFileLoader("telegram_admin_bot_autopilot_suggestions", str(script))
    spec = spec_from_loader("telegram_admin_bot_autopilot_suggestions", loader)
    assert spec is not None
    bot = module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["telegram_admin_bot_autopilot_suggestions"] = bot
    spec.loader.exec_module(bot)  # type: ignore

    monkeypatch.setattr(bot, "ADMIN_TELEGRAM_IDS", {123})
    monkeypatch.setattr(bot, "admin_lang", {123: "en"})

    def _backend_request(method, path, json_body=None):
        if path == "/api/v1/admin/autopilot/suggestions":
            return {
                "suggestions": [
                    {
                        "id": "clear_cache",
                        "title": "Clear Redis cache",
                        "reason": "Cache hit ratio is low",
                        "impact": "medium",
                        "risk": "low",
                        "action_endpoint": "/api/v1/admin/system/clear-cache",
                    }
                ]
            }
        return {}

    monkeypatch.setattr(bot, "backend", types.SimpleNamespace(request=_backend_request))
    monkeypatch.setattr(bot, "tg_answer_callback", lambda *a, **k: None)
    edited = {"text": "", "kb": None}
    monkeypatch.setattr(bot, "tg_edit", lambda chat_id, msg_id, text, keyboard=None: edited.update({"text": text, "kb": keyboard}))

    bot.route_callback("m:autopilot_suggestions", chat_id=1, msg_id=2, user_id=123, cbq_id="cbq")
    assert "Clear Redis cache" in edited["text"]
    assert any(btn.get("callback_data") == "c:auto:clear_cache" for row in edited["kb"] for btn in row)


def test_callback_routing_autopilot_confirm_and_execute(monkeypatch):
    from importlib.machinery import SourceFileLoader
    from importlib.util import module_from_spec, spec_from_loader
    from pathlib import Path
    import sys
    import types

    script = Path(__file__).resolve().parents[1] / "scripts" / "telegram_admin_bot.py"
    loader = SourceFileLoader("telegram_admin_bot_autopilot_execute", str(script))
    spec = spec_from_loader("telegram_admin_bot_autopilot_execute", loader)
    assert spec is not None
    bot = module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["telegram_admin_bot_autopilot_execute"] = bot
    spec.loader.exec_module(bot)  # type: ignore

    monkeypatch.setattr(bot, "ADMIN_TELEGRAM_IDS", {123})
    monkeypatch.setattr(bot, "admin_lang", {123: "en"})
    calls = []

    def _backend_request(method, path, json_body=None):
        calls.append((method, path, json_body))
        if path == "/api/v1/admin/autopilot/suggestions":
            return {
                "suggestions": [
                    {
                        "id": "clear_cache",
                        "title": "Clear Redis cache",
                        "reason": "Cache hit ratio is low",
                        "impact": "medium",
                        "risk": "low",
                        "action_endpoint": "/api/v1/admin/system/clear-cache",
                    }
                ]
            }
        if path == "/api/v1/admin/autopilot/execute":
            return {"ok": True, "status": "executed", "action_id": "clear_cache", "result": {"ok": True}}
        return {}

    monkeypatch.setattr(bot, "backend", types.SimpleNamespace(request=_backend_request))
    monkeypatch.setattr(bot, "tg_answer_callback", lambda *a, **k: None)
    monkeypatch.setattr(bot, "tg_edit", lambda *a, **k: None)

    bot.route_callback("c:auto:clear_cache", chat_id=1, msg_id=2, user_id=123, cbq_id="cbq")
    bot.route_callback("x:auto:clear_cache", chat_id=1, msg_id=2, user_id=123, cbq_id="cbq")
    assert ("POST", "/api/v1/admin/autopilot/execute", {"action_id": "clear_cache", "confirm": True}) in calls


def test_callback_routing_demo_mode_menu(monkeypatch):
    bot = _load_bot_module("telegram_admin_bot_demo_mode_menu")
    monkeypatch.setattr(bot, "ADMIN_TELEGRAM_IDS", {123})
    monkeypatch.setattr(bot, "admin_lang", {123: "en"})

    def _backend_request(method, path, json_body=None):
        if method == "GET" and path == "/api/v1/admin/demo-mode":
            return {"enabled": False, "demo_profiles": 2, "demo_conversations": 1, "metrics": {}}
        return {}

    import types

    monkeypatch.setattr(bot, "backend", types.SimpleNamespace(request=_backend_request))
    monkeypatch.setattr(bot, "tg_answer_callback", lambda *a, **k: None)
    edits: list[tuple[str, list[list[dict[str, str]]] | None]] = []
    monkeypatch.setattr(bot, "tg_edit", lambda chat_id, msg_id, text, keyboard=None: edits.append((text, keyboard)))

    bot.route_callback("m:demo", chat_id=1, msg_id=2, user_id=123, cbq_id="cbq")
    assert edits
    assert "Demo Mode" in edits[0][0]
    flat = [btn for row in (edits[0][1] or []) for btn in row]
    cbs = {b.get("callback_data") for b in flat}
    assert "c:demo_enable" in cbs
    assert "c:demo_disable" in cbs
    assert "c:demo_regen" in cbs
    assert "c:demo_clear" in cbs
    assert "m:demo_metrics" in cbs
