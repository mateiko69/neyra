from __future__ import annotations

import types

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.deps import get_admin_user, get_admin_actor
from app.api.v1.endpoints.admin import router as admin_router
from app.services.telegram_menu_qa import scan_telegram_bot_module


class DummyAdmin:
    id = 999
    email = "admin@example.com"


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(admin_router, prefix="/api/v1/admin")
    app.dependency_overrides[get_admin_user] = lambda: DummyAdmin()
    app.dependency_overrides[get_admin_actor] = lambda: DummyAdmin()
    return TestClient(app)


def test_fallback_render_ui_includes_back():
    from importlib.machinery import SourceFileLoader
    from importlib.util import module_from_spec, spec_from_loader
    from pathlib import Path
    import sys

    script = Path(__file__).resolve().parents[1] / "scripts" / "telegram_admin_bot.py"
    loader = SourceFileLoader("telegram_admin_bot_fb", str(script))
    spec = spec_from_loader("telegram_admin_bot_fb", loader)
    assert spec is not None
    bot = module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["telegram_admin_bot_fb"] = bot
    spec.loader.exec_module(bot)  # type: ignore[attr-defined]

    txt, kb = bot.fallback_render_ui(42, "No reports yet", "m:safety")
    assert "No reports yet" in txt
    assert kb and kb[0][0].get("callback_data") == "m:safety"


def test_menu_qa_scan_endpoint_shape():
    c = _client()
    r = c.get("/api/v1/admin/telegram-menu-qa/scan")
    assert r.status_code == 200
    j = r.json()
    assert j["status"] in {"pass", "warning"}
    assert j["summary"]["render_errors"] == 0
    assert "summary" in j and "issues" in j
    for k in [
        "menus_checked",
        "buttons_checked",
        "callbacks_checked",
        "missing_handlers",
        "missing_translations",
        "unsafe_actions",
        "render_errors",
        "unsafe_callbacks",
    ]:
        assert k in j["summary"]
    assert isinstance(j["summary"]["unsafe_callbacks"], list)
    for issue in j["issues"]:
        if issue.get("type") == "unsafe_action":
            assert issue.get("expected_confirm")
            assert issue.get("risk")
            assert "source_menus" in issue


def test_menu_qa_missing_handler_detection():
    bot = types.SimpleNamespace()
    bot.STRINGS = {"en": {"back": "Back"}, "uk": {"back": "Назад"}}
    bot.admin_lang = {123: "en"}

    def render_fake_menu(user_id: int):
        return ("x", [[{"text": "Go", "callback_data": "m:missing"}], [{"text": "Back", "callback_data": "m:home"}]])

    bot.render_fake_menu = render_fake_menu

    def route_callback(data: str, chat_id: int, msg_id: int, user_id: int, cbq_id: str):
        # fallthrough => unknown action
        bot.tg_answer_callback(cbq_id, "Unknown action.")

    bot.route_callback = route_callback
    bot.tg_answer_callback = lambda *a, **k: None
    bot.tg_edit = lambda *a, **k: None

    out = scan_telegram_bot_module(bot)
    assert out["summary"]["missing_handlers"] >= 1


def test_menu_qa_missing_translation_detection():
    bot = types.SimpleNamespace()
    bot.STRINGS = {"en": {"a": "A"}, "uk": {"a": "A", "missing": "X"}}
    bot.admin_lang = {123: "en"}
    bot.route_callback = lambda *a, **k: None
    bot.tg_answer_callback = lambda *a, **k: None
    bot.tg_edit = lambda *a, **k: None
    bot.render_menu = lambda: ("x", [[{"text": "Back", "callback_data": "m:home"}]])

    out = scan_telegram_bot_module(bot)
    assert out["summary"]["missing_translations"] >= 1


def test_menu_qa_unsafe_action_issues_are_warnings_not_critical():
    bot = types.SimpleNamespace()
    bot.STRINGS = {"en": {"back": "Back"}, "uk": {"back": "Назад"}}
    bot.admin_lang = {123: "en"}

    def render_danger_menu(user_id: int):
        return (
            "x",
            [
                [{"text": "Clear", "callback_data": "c:clear_cache"}],
                [{"text": "Confirm", "callback_data": "x:clear_cache_yes"}],
                [{"text": "Back", "callback_data": "m:home"}],
            ],
        )

    bot.render_danger_menu = render_danger_menu

    def route_callback(data: str, chat_id: int, msg_id: int, user_id: int, cbq_id: str) -> None:
        if data == "c:clear_cache":
            bot.tg_edit(chat_id, msg_id, "confirm?", [[{"text": "yes", "callback_data": "x:clear_cache_yes"}]])
            return
        if data == "m:home":
            return
        bot.tg_answer_callback(cbq_id, "Unknown action.")

    bot.route_callback = route_callback
    bot.tg_answer_callback = lambda *a, **k: None
    bot.tg_edit = lambda *a, **k: None

    out = scan_telegram_bot_module(bot)
    unsafe = [i for i in out["issues"] if i.get("type") == "unsafe_action"]
    assert not unsafe


def test_menu_qa_real_bot_scan_low_unsafe_heuristics():
    from importlib.machinery import SourceFileLoader
    from importlib.util import module_from_spec, spec_from_loader
    from pathlib import Path
    import sys

    script = Path(__file__).resolve().parents[1] / "scripts" / "telegram_admin_bot.py"
    loader = SourceFileLoader("telegram_admin_bot_qa_real", str(script))
    spec = spec_from_loader("telegram_admin_bot_qa_real", loader)
    assert spec is not None
    bot = module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["telegram_admin_bot_qa_real"] = bot
    spec.loader.exec_module(bot)  # type: ignore[attr-defined]
    setattr(bot, "tg_call", lambda *a, **k: {"ok": True, "result": {}})
    setattr(bot, "backend", type("B", (), {"request": lambda *a, **k: {}})())

    out = scan_telegram_bot_module(bot)
    assert out["summary"]["unsafe_actions"] <= 2
    assert out["summary"]["render_errors"] == 0


def test_menu_qa_flags_unsafe_when_confirm_token_missing():
    bot = types.SimpleNamespace()
    bot.STRINGS = {"en": {"back": "Back"}, "uk": {"back": "Назад"}}
    bot.admin_lang = {123: "en"}

    def render_danger_menu(user_id: int):
        return ("x", [[{"text": "Clear", "callback_data": "c:clear_cache"}], [{"text": "Back", "callback_data": "m:home"}]])

    bot.render_danger_menu = render_danger_menu

    def route_callback(data: str, chat_id: int, msg_id: int, user_id: int, cbq_id: str) -> None:
        if data in {"c:clear_cache", "m:home"}:
            return
        bot.tg_answer_callback(cbq_id, "Unknown action.")

    bot.route_callback = route_callback
    bot.tg_answer_callback = lambda *a, **k: None
    bot.tg_edit = lambda *a, **k: None

    out = scan_telegram_bot_module(bot)
    unsafe = [i for i in out["issues"] if i.get("type") == "unsafe_action"]
    assert unsafe
    assert all(i.get("severity") == "warning" for i in unsafe)
    u0 = unsafe[0]
    assert u0.get("callback") == "c:clear_cache"
    assert "clear_cache_yes" in (u0.get("expected_confirm") or "")
    assert u0.get("risk")


def test_all_render_functions_run_with_no_args():
    """Every render_* must be callable with zero arguments and return (text, keyboard)."""
    from importlib.machinery import SourceFileLoader
    from importlib.util import module_from_spec, spec_from_loader
    from pathlib import Path
    import sys

    script = Path(__file__).resolve().parents[1] / "scripts" / "telegram_admin_bot.py"
    loader = SourceFileLoader("telegram_admin_bot_render_smoke", str(script))
    spec = spec_from_loader("telegram_admin_bot_render_smoke", loader)
    assert spec is not None
    bot = module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["telegram_admin_bot_render_smoke"] = bot
    spec.loader.exec_module(bot)  # type: ignore[attr-defined]
    setattr(bot, "tg_call", lambda *a, **k: {"ok": True, "result": {}})
    setattr(bot, "backend", type("B", (), {"request": lambda *a, **k: {}})())

    for name in sorted(dir(bot)):
        if not name.startswith("render_"):
            continue
        fn = getattr(bot, name, None)
        if not callable(fn):
            continue
        res = fn()
        assert isinstance(res, tuple) and len(res) == 2, f"{name} must return (text, kb)"
        text, kb = res
        assert isinstance(text, str), f"{name} text must be str"
        assert isinstance(kb, list), f"{name} kb must be list"


def test_menu_qa_callback_length_check():
    bot = types.SimpleNamespace()
    bot.STRINGS = {"en": {"back": "Back"}, "uk": {"back": "Назад"}}
    bot.admin_lang = {123: "en"}

    long_cb = "m:" + ("x" * 100)
    bot.render_menu = lambda: ("x", [[{"text": "Long", "callback_data": long_cb}], [{"text": "Back", "callback_data": "m:home"}]])
    bot.route_callback = lambda *a, **k: None
    bot.tg_answer_callback = lambda *a, **k: None
    bot.tg_edit = lambda *a, **k: None

    out = scan_telegram_bot_module(bot)
    assert any(i["type"] == "unknown_callback" and i["severity"] == "warning" for i in out["issues"])

