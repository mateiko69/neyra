"""
End-to-end smoke for upgraded Telegram admin bot routing (no real Telegram API).

Exercises /start, Command Center, AI Assistant flows, diagnostics, More… legacy menu,
keyboard shape, navigation escape hatches, and HTML heuristics.
"""

from __future__ import annotations

import types
from importlib.machinery import SourceFileLoader
from importlib.util import module_from_spec, spec_from_loader
from pathlib import Path
import sys

from tests.telegram_qa_utils import (
    assert_inline_keyboard_is_rows,
    collect_callback_data,
    keyboard_has_nav_escape,
    message_fits_telegram_limit,
    telegram_html_allowlist_ok,
    telegram_html_pairs_balanced,
)


def _load_bot(name: str):
    script = Path(__file__).resolve().parents[1] / "scripts" / "telegram_admin_bot.py"
    loader = SourceFileLoader(name, str(script))
    spec = spec_from_loader(name, loader)
    assert spec is not None
    bot = module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = bot
    spec.loader.exec_module(bot)  # type: ignore[attr-defined]
    return bot


def _fake_backend_router(bot):
    """Replace bot.backend.request with deterministic JSON for smoke paths."""

    def request(method: str, path: str, json_body: dict | None = None):  # noqa: ARG001
        if path.startswith("/api/v1/admin/command-center/home"):
            return {
                "status": "healthy",
                "today": {
                    "active_users": 1,
                    "new_users": 0,
                    "matches": 0,
                    "messages": 0,
                    "ai_calls": 0,
                    "premium_users": 0,
                    "open_reports": 0,
                },
                "top_recommendation": {"title": "T", "reason": "R", "action": "A"},
            }
        if path.startswith("/api/v1/admin/telegram/diagnostics"):
            return {
                "api_status": "ok",
                "database_status": "ok",
                "gemini_status": "disabled",
                "telegram_diagnostic_lines": [
                    "[runtime_verified] API",
                    "[runtime_verified] DB",
                    "[partial] AI",
                    "[static_verified] modes",
                ],
                "telegram_active_modes": {"ai_suggestions": True},
                "telegram_last_errors": [],
                "telegram_error_tags": "[runtime_verified]",
            }
        if "/telegram/ai/chat-copilot" in path:
            return {
                "options": [
                    {"text": "Hello option one?", "style": "light", "label": "L"},
                    {"text": "Playful option two?", "style": "flirty", "label": "F"},
                    {"text": "Deep option three?", "style": "deep", "label": "D"},
                ],
                "limited": False,
                "fallback": False,
                "readiness_score": None,
            }
        if "/telegram/ai/meeting-ready" in path:
            return {
                "readiness_score": 72,
                "closer_stage": "warming",
                "suggestions": ["Coffee?", "Walk?", "Drinks?"],
                "show_moment_hint": False,
                "telegram_closer_hint": True,
                "telegram_threshold": 60,
            }
        if "/telegram/ai/start-strategy" in path:
            return {
                "strategy": "Ask about shared interests",
                "confidence": 80,
                "hooks": ["travel"],
                "openers": [{"style": "light", "text": "Hi — how was your weekend?"}],
            }
        if "/telegram/ai/timed-replies" in path:
            return {
                "options": [{"style": "light", "text": "Ping one?"}, {"style": "flirty", "text": "Ping two?"}],
                "locale": "en",
                "source": "fallback",
            }
        if "/telegram/ai/improve-reply" in path:
            return {"variants": [{"text": "Polished A", "style": "safe"}], "meta": {"limited": False, "locale": "en"}}
        if "/telegram/analytics/track" in path:
            return {"ok": True}
        return {"ok": True}

    bot.backend.request = request  # type: ignore[method-assign]


def test_smoke_start_and_command_center_keyboard(monkeypatch):
    bot = _load_bot("tg_e2e_start")
    monkeypatch.setattr(bot, "ADMIN_TELEGRAM_IDS", {123})
    monkeypatch.setattr(bot, "ADMIN_BOT_SERVICE_TOKEN", "token")
    monkeypatch.setattr(bot, "admin_lang", {123: "en"})
    _fake_backend_router(bot)

    sent: list[tuple[str, object]] = []

    def tg_send(chat_id, text, keyboard=None):
        sent.append((text, keyboard))

    monkeypatch.setattr(bot, "tg_send", tg_send)
    bot.route_message("/start", chat_id=1, user_id=123)

    assert sent, "expected tg_send"
    text, kb = sent[-1][0], sent[-1][1]
    assert "Command Center" in text or "NEYRA" in text
    assert_inline_keyboard_is_rows(kb)
    cbs = collect_callback_data(kb)
    assert "m:more" in cbs
    assert "m:ai" in cbs
    assert keyboard_has_nav_escape(kb)
    ok, why = telegram_html_allowlist_ok(text)
    assert ok, why
    assert message_fits_telegram_limit(text)


def test_smoke_non_admin_rejected(monkeypatch):
    bot = _load_bot("tg_e2e_denied")
    monkeypatch.setattr(bot, "ADMIN_TELEGRAM_IDS", {999})
    monkeypatch.setattr(bot, "ADMIN_BOT_SERVICE_TOKEN", "token")
    sent: list[str] = []

    def tg_send(chat_id, text, keyboard=None):
        sent.append(text)

    monkeypatch.setattr(bot, "tg_send", tg_send)
    bot.route_message("/start", chat_id=1, user_id=123)
    assert sent and "access" in sent[-1].lower()


def test_smoke_ai_flow_copilot_meeting_improve(monkeypatch):
    bot = _load_bot("tg_e2e_ai")
    monkeypatch.setattr(bot, "ADMIN_TELEGRAM_IDS", {123})
    monkeypatch.setattr(bot, "ADMIN_BOT_SERVICE_TOKEN", "token")
    monkeypatch.setattr(bot, "admin_lang", {123: "en"})
    _fake_backend_router(bot)

    tracks: list[tuple[str, dict]] = []

    def capture_track(name: str, *, telegram_user_id: int, viewer_user_id: int | None = None, payload=None):
        tracks.append((name, {"telegram_user_id": telegram_user_id, "viewer_user_id": viewer_user_id, "payload": payload}))

    monkeypatch.setattr(bot, "telegram_track", capture_track)

    edits: list[tuple[str, object]] = []

    def tg_edit(cid, mid, text, keyboard=None):
        edits.append((text, keyboard))

    monkeypatch.setattr(bot, "tg_edit", tg_edit)
    monkeypatch.setattr(bot, "tg_send", lambda *a, **k: None)
    monkeypatch.setattr(bot, "tg_answer_callback", lambda *a, **k: None)

    bot.ai_ctx_set(1, 123, viewer_uid=5, partner_uid=7)

    bot.route_callback("m:ai", chat_id=1, msg_id=10, user_id=123, cbq_id="x")
    assert edits, "ai hub"
    assert_inline_keyboard_is_rows(edits[-1][1])
    assert keyboard_has_nav_escape(edits[-1][1])

    bot.route_callback("a:g", chat_id=1, msg_id=10, user_id=123, cbq_id="x")
    assert any("Copilot" in e[0] for e in edits)
    assert any("ai_used" == t[0] for t in tracks)

    bot.route_callback("a:u:1", chat_id=1, msg_id=10, user_id=123, cbq_id="x")
    assert any("ai_suggestion_used" == t[0] for t in tracks)

    bot.route_callback("a:ns", chat_id=1, msg_id=10, user_id=123, cbq_id="x")

    bot.route_callback("a:mr", chat_id=1, msg_id=10, user_id=123, cbq_id="x")
    assert any("going well" in e[0].lower() or "🔥" in e[0] for e in edits)

    bot.route_callback("a:im", chat_id=1, msg_id=10, user_id=123, cbq_id="x")
    bot.route_message("draft text here please", chat_id=1, user_id=123)


def test_smoke_ai_improve_message(monkeypatch):
    bot = _load_bot("tg_e2e_improve")
    monkeypatch.setattr(bot, "ADMIN_TELEGRAM_IDS", {123})
    monkeypatch.setattr(bot, "ADMIN_BOT_SERVICE_TOKEN", "token")
    monkeypatch.setattr(bot, "admin_lang", {123: "en"})
    _fake_backend_router(bot)

    last: dict[str, object] = {}

    def tg_send(chat_id, text, keyboard=None):
        last["text"] = text
        last["kb"] = keyboard

    monkeypatch.setattr(bot, "tg_send", tg_send)
    monkeypatch.setattr(bot, "tg_answer_callback", lambda *a, **k: None)

    bot.ai_ctx_set(1, 123, viewer_uid=5, partner_uid=7)
    bot.set_input(1, 123, "ai_improve_text", {})
    bot.route_message("My draft line", chat_id=1, user_id=123)

    assert "Improve" in str(last.get("text", ""))
    assert_inline_keyboard_is_rows(last.get("kb"))


def test_smoke_diagnostics_and_legacy_more(monkeypatch):
    bot = _load_bot("tg_e2e_diag")
    monkeypatch.setattr(bot, "ADMIN_TELEGRAM_IDS", {123})
    monkeypatch.setattr(bot, "ADMIN_BOT_SERVICE_TOKEN", "token")
    monkeypatch.setattr(bot, "admin_lang", {123: "en"})
    _fake_backend_router(bot)

    edits: list[tuple[str, object]] = []

    def tg_edit(cid, mid, text, keyboard=None):
        edits.append((text, keyboard))

    monkeypatch.setattr(bot, "tg_edit", tg_edit)
    monkeypatch.setattr(bot, "tg_answer_callback", lambda *a, **k: None)

    bot.route_callback("m:diag", chat_id=1, msg_id=2, user_id=123, cbq_id="x")
    diag_text = edits[-1][0]
    assert "Product diagnostics" in diag_text or "diagnostic" in diag_text.lower()
    assert "[runtime_verified]" in diag_text or "API" in diag_text
    ok, _ = telegram_html_allowlist_ok(diag_text)
    assert ok
    assert_inline_keyboard_is_rows(edits[-1][1])
    assert keyboard_has_nav_escape(edits[-1][1])

    bot.route_callback("m:more", chat_id=1, msg_id=2, user_id=123, cbq_id="x")
    more_text, more_kb = edits[-1][0], edits[-1][1]
    assert "section" in more_text.lower() or "Choose" in more_text or "Оберіть" in more_text
    assert_inline_keyboard_is_rows(more_kb)
    legacy_cbs = collect_callback_data(more_kb)
    assert "m:stats" in legacy_cbs and "m:demo" in legacy_cbs


def test_smoke_register_visible_callbacks_resolve(monkeypatch):
    """Fire product_root_menu + AI hub callbacks (except viewer/partner prompts) — no unknown_action."""
    bot = _load_bot("tg_e2e_callbacks")
    monkeypatch.setattr(bot, "ADMIN_TELEGRAM_IDS", {123})
    monkeypatch.setattr(bot, "ADMIN_BOT_SERVICE_TOKEN", "token")
    monkeypatch.setattr(bot, "admin_lang", {123: "en"})
    _fake_backend_router(bot)

    unknown: list[str] = []

    def tg_answer_callback(cid, text="", *, show_alert=False):
        if text and "unknown" in str(text).lower():
            unknown.append(str(text))

    monkeypatch.setattr(bot, "tg_answer_callback", tg_answer_callback)
    monkeypatch.setattr(bot, "tg_edit", lambda *a, **k: None)

    kb_home = bot.product_root_menu(123)
    for cb in collect_callback_data(kb_home):
        bot.route_callback(cb, 1, 2, 123, "q")

    bot.ai_ctx_set(1, 123, viewer_uid=1, partner_uid=2)
    kb_ai = bot.render_ai_hub(123, 1)[1]
    for cb in collect_callback_data(kb_ai):
        if cb in {"a:v", "a:p"}:
            continue
        bot.route_callback(cb, 1, 2, 123, "q")

    assert not unknown, f"unexpected unknown callbacks: {unknown[:5]}"


def test_html_escape_heuristic_on_render_outputs(monkeypatch):
    bot = _load_bot("tg_e2e_html")
    monkeypatch.setattr(bot, "ADMIN_TELEGRAM_IDS", {123})
    monkeypatch.setattr(bot, "ADMIN_BOT_SERVICE_TOKEN", "token")
    monkeypatch.setattr(bot, "admin_lang", {123: "en"})
    _fake_backend_router(bot)

    text, kb = bot.render_product_diagnostics(123)
    ok, why = telegram_html_allowlist_ok(text)
    assert ok, why
    ok2, why2 = telegram_html_pairs_balanced(text)
    assert ok2, why2
    assert "<script" not in text.lower()
    assert_inline_keyboard_is_rows(kb)
