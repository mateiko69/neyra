from __future__ import annotations

import os
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable


def _menu_qa_dev_log(msg: str) -> None:
    env = str(os.getenv("ENV") or os.getenv("NEYRA_ENV") or os.getenv("APP_ENV") or "").strip().lower()
    if env not in {"production", "prod"}:
        print(f"[menu_qa_debug] {msg}", flush=True)


def _keyboards_offer_confirm(keyboards: list[Any]) -> bool:
    """True if any captured tg_edit keyboard exposes a confirm token (x:*yes* / x:auto:*)."""
    for kb in keyboards:
        for row in kb or []:
            if not isinstance(row, list):
                continue
            for btn in row:
                if not isinstance(btn, dict):
                    continue
                cdata = str(btn.get("callback_data") or "").lower()
                if "yes" in cdata or cdata.startswith("x:auto:"):
                    return True
    return False


# Callbacks that are flagged by keyword heuristics but are safe (read-only / non-destructive UX).
MENU_QA_UNSAFE_ALLOWLIST_EXACT: frozenset[str] = frozenset()
MENU_QA_UNSAFE_ALLOWLIST_PREFIXES: tuple[str, ...] = ()

# Renderers that require curated payload / routing context; scanning with fn()/fn(uid) is not meaningful.
MENU_QA_SKIP_RENDERERS: frozenset[str] = frozenset({"render_engagement_generated_detail"})


def _allowlisted_safe(cb: str) -> bool:
    c = str(cb or "").strip()
    if c in MENU_QA_UNSAFE_ALLOWLIST_EXACT:
        return True
    return any(c.startswith(p) for p in MENU_QA_UNSAFE_ALLOWLIST_PREFIXES)


def _expected_confirm_hint(cb: str) -> str:
    c = str(cb or "").strip()
    if c == "c:clear_cache":
        return "x:clear_cache_yes"
    if c == "c:run_migrations":
        return "x:run_migrations_yes"
    if c == "c:backup_db":
        return "x:backup_db_yes"
    if c == "c:backup_create":
        return "x:backup_create_yes"
    if c == "c:l10n_fix":
        return "x:l10n_fix_yes"
    if c == "c:lagent_fix":
        return "x:lagent_fix_yes"
    if c == "c:premium_grant_all":
        return "x:premium_grant_all_yes"
    if c == "m:match_quality_recompute":
        return "x:match_quality_recompute_yes"
    if c.startswith("c:prem:"):
        return "x:prem_yes:<uid>:<days>"
    if c.startswith("c:revoke:"):
        return "x:revoke_yes:<uid>"
    if c.startswith("c:memreset:"):
        return "x:memreset_yes:<uid>"
    if c.startswith("c:rep_dismiss:"):
        return "x:rep_dismiss_yes:<rid>"
    if c.startswith("c:rep_ban:"):
        return "x:rep_ban_yes:<rid>:<uid>"
    if c.startswith("c:unban:"):
        return "x:unban_yes:<uid>"
    if c.startswith("c:auto:"):
        return "x:auto:<action_id> (confirm step) or static x:*yes*"
    if c == "c:demo_enable":
        return "x:demo_enable_yes"
    if c == "c:demo_disable":
        return "x:demo_disable_yes"
    if c == "c:demo_regen":
        return "x:demo_regen_yes"
    if c == "c:demo_clear":
        return "x:demo_clear_yes"
    return "x:<action>_yes (confirm token on second step)"


def _risk_description(cb: str) -> str:
    c = str(cb or "").strip()
    if c == "c:clear_cache":
        return "Clears Redis cache (flushdb)."
    if c == "c:run_migrations":
        return "Runs Alembic database migrations."
    if c in {"c:backup_db", "c:backup_create"}:
        return "Creates or exports database backup."
    if c == "c:l10n_fix":
        return "Runs localization safe auto-fix (writes locale files)."
    if c == "c:lagent_fix":
        return "Runs localization agent auto-fix (writes locale files)."
    if c == "c:premium_grant_all":
        return "Grants premium to many dev users."
    if c == "m:match_quality_recompute":
        return "Recomputes match compatibility scores (server work)."
    if c.startswith("c:prem:"):
        return "Grants premium to a user."
    if c.startswith("c:revoke:"):
        return "Revokes premium from a user."
    if c.startswith("c:memreset:"):
        return "Resets AI conversation memory for a user."
    if c.startswith("c:rep_dismiss:"):
        return "Dismisses a safety report."
    if c.startswith("c:rep_ban:"):
        return "Bans a user from a report resolution flow."
    if c.startswith("c:unban:"):
        return "Unbans a user."
    if c.startswith("c:auto:"):
        return "Runs an Autopilot admin action (may call backend with confirm)."
    if c in {"c:demo_enable", "c:demo_disable", "c:demo_regen", "c:demo_clear"}:
        return "Changes demo mode state or demo seed data (admin-only)."
    return "Destructive or elevated admin action."


@dataclass
class QaIssue:
    severity: str  # critical|warning|info
    type: str  # missing_handler|missing_translation|unsafe_action|render_error|missing_back_button|unknown_callback
    menu: str
    callback: str
    message: str
    suggested_fix: str
    risk: str = ""
    expected_confirm: str = ""
    source_menus: list[str] = field(default_factory=list)


def _is_back_label(text: str) -> bool:
    t = (text or "").strip().lower()
    return ("back" in t) or ("назад" in t) or ("🔙" in t) or ("⬅️" in t)


def _iter_buttons(kb: Any) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    if not isinstance(kb, list):
        return out
    for row in kb:
        if not isinstance(row, list):
            continue
        for btn in row:
            if isinstance(btn, dict):
                out.append(btn)
    return out


def _dangerous_callback(cb: str) -> bool:
    """
    Immediate admin actions that should show an in-keyboard confirm on the same step.
    Excludes multi-step flows (ban reason, promo text, release text, backup-restore phrase)
    where confirmation appears only after user input — those are not static-keyboard checks.
    """
    c = str(cb or "").strip()
    if c in {
        "c:clear_cache",
        "c:run_migrations",
        "c:backup_db",
        "c:backup_create",
        "c:l10n_fix",
        "c:lagent_fix",
        "c:premium_grant_all",
        "m:match_quality_recompute",
        "c:demo_enable",
        "c:demo_disable",
        "c:demo_regen",
        "c:demo_clear",
    }:
        return True
    prefixes = (
        "c:prem:",
        "c:revoke:",
        "c:memreset:",
        "c:rep_dismiss:",
        "c:rep_ban:",
        "c:unban:",
        "c:auto:",
    )
    return any(c.startswith(p) for p in prefixes)


def _has_matching_confirm_step(cb: str, collected: set[str]) -> bool:
    """
    Each dangerous c:* / m:* entry must have a second-step confirm in keyboards:
    explicit x:*_yes / x:auto:* (server uses confirm:true on POST).
    """
    c = str(cb or "").strip()

    if c == "c:clear_cache":
        return "x:clear_cache_yes" in collected
    if c == "c:run_migrations":
        return "x:run_migrations_yes" in collected
    if c == "c:backup_db":
        return "x:backup_db_yes" in collected
    if c == "c:backup_create":
        return "x:backup_create_yes" in collected
    if c == "c:l10n_fix":
        return "x:l10n_fix_yes" in collected
    if c == "c:lagent_fix":
        return "x:lagent_fix_yes" in collected
    if c == "c:premium_grant_all":
        return "x:premium_grant_all_yes" in collected
    if c == "m:match_quality_recompute":
        return "x:match_quality_recompute_yes" in collected

    if c == "c:demo_enable":
        return "x:demo_enable_yes" in collected
    if c == "c:demo_disable":
        return "x:demo_disable_yes" in collected
    if c == "c:demo_regen":
        return "x:demo_regen_yes" in collected
    if c == "c:demo_clear":
        return "x:demo_clear_yes" in collected

    if c.startswith("c:prem:"):
        return any(x.startswith("x:prem_yes:") for x in collected)
    if c.startswith("c:revoke:"):
        return any(x.startswith("x:revoke_yes:") for x in collected)
    if c.startswith("c:memreset:"):
        return any(x.startswith("x:memreset_yes:") for x in collected)
    if c.startswith("c:rep_dismiss:"):
        return any(x.startswith("x:rep_dismiss_yes:") for x in collected)
    if c.startswith("c:rep_ban:"):
        return any(x.startswith("x:rep_ban_yes:") for x in collected)
    if c.startswith("c:unban:"):
        return any(x.startswith("x:unban_yes:") for x in collected)
    if c.startswith("c:auto:"):
        return any(x.startswith("x:auto:") for x in collected)

    return False


def scan_telegram_bot_module(
    bot: Any,
    *,
    dangerous_callbacks: set[str] | None = None,
    max_callback_len: int = 64,
) -> dict[str, Any]:
    """
    Scan a loaded telegram_admin_bot module.
    - Calls render_* functions (best-effort) to collect keyboards/callback_data.
    - Simulates routing by calling route_callback with stubbed tg/backend.
    """
    _ = dangerous_callbacks  # legacy API; use _dangerous_callback / _has_matching_confirm_step

    issues: list[QaIssue] = []
    menus_checked = 0
    buttons_checked = 0
    callbacks_checked = 0

    # Translation parity check
    missing_translations = 0
    try:
        strings = getattr(bot, "STRINGS", {})
        uk_keys = set((strings.get("uk") or {}).keys())
        en_keys = set((strings.get("en") or {}).keys())
        missing = sorted((uk_keys ^ en_keys))
        missing_translations = len(missing)
        for k in missing[:50]:
            issues.append(
                QaIssue(
                    severity="warning",
                    type="missing_translation",
                    menu="translations",
                    callback="",
                    message=f"Translation key missing in uk/en parity: {k}",
                    suggested_fix="Ensure STRINGS['uk'] and STRINGS['en'] contain the same keys.",
                )
            )
    except Exception as e:
        issues.append(
            QaIssue(
                severity="warning",
                type="missing_translation",
                menu="translations",
                callback="",
                message=f"Failed to check translations: {e}",
                suggested_fix="Ensure STRINGS dict exists and is well-formed.",
            )
        )

    # Collect renderers (menus/screens)
    renderers: list[tuple[str, Callable]] = []
    for name in dir(bot):
        if not name.startswith("render_"):
            continue
        fn = getattr(bot, name, None)
        if callable(fn):
            renderers.append((name, fn))

    # Some renderers require user_id; some don't. We'll try both.
    collected_callbacks: set[str] = set()
    callback_sources: dict[str, set[str]] = defaultdict(set)
    missing_back_button = 0

    for (name, fn) in renderers:
        if name in MENU_QA_SKIP_RENDERERS:
            continue
        menus_checked += 1
        try:
            res = None
            try:
                res = fn()
            except TypeError:
                try:
                    res = fn(123)
                except TypeError:
                    res = None
            if not (isinstance(res, tuple) and len(res) == 2):
                continue
            _text, kb = res
            btns = _iter_buttons(kb)
            buttons_checked += len(btns)
            has_back = False
            for b in btns:
                cb = str(b.get("callback_data") or "")
                tx = str(b.get("text") or "")
                if cb:
                    collected_callbacks.add(cb)
                    callback_sources[cb].add(name)
                if cb.startswith("m:") and _is_back_label(tx):
                    has_back = True
            if btns and not has_back and ("menu" in name or name.endswith("_menu")):
                missing_back_button += 1
                issues.append(
                    QaIssue(
                        severity="warning",
                        type="missing_back_button",
                        menu=name,
                        callback="",
                        message="Menu renderer has no obvious Back button.",
                        suggested_fix="Add a Back button to home or parent menu.",
                    )
                )
        except Exception as e:
            issues.append(
                QaIssue(
                    severity="warning",
                    type="render_error",
                    menu=name,
                    callback="",
                    message=f"Renderer raised: {e}",
                    suggested_fix="Ensure render guards wrap this menu (NEYRA: render_* should not throw).",
                )
            )

    # Callback checks
    missing_handlers = 0
    unsafe_actions = 0

    # Stubs to prevent network calls/crashes.
    seen_unknown_action = 0

    def _stub_answer_callback(_cbq_id: str, text: str = "", **_kwargs: Any) -> None:
        nonlocal seen_unknown_action
        if (text or "").strip().lower() in {"unknown action.", "невідома дія."}:
            seen_unknown_action += 1

    def _stub_edit(*_a, **_k) -> None:
        return None

    # Monkeypatching module attributes (best-effort)
    setattr(bot, "tg_answer_callback", _stub_answer_callback)
    setattr(bot, "tg_edit", _stub_edit)

    # Ensure language set to English for deterministic "Unknown action."
    try:
        getattr(bot, "admin_lang")[123] = "en"
    except Exception:
        pass

    _orig_is_admin = getattr(bot, "is_admin", None)
    if callable(_orig_is_admin):
        setattr(bot, "is_admin", lambda _uid: True)
    try:
        for cb in sorted(collected_callbacks):
            callbacks_checked += 1
            if len(cb.encode("utf-8")) > max_callback_len:
                issues.append(
                    QaIssue(
                        severity="warning",
                        type="unknown_callback",
                        menu="callback_data",
                        callback=cb,
                        message=f"callback_data too long ({len(cb.encode('utf-8'))} bytes)",
                        suggested_fix="Shorten callback_data to <= 64 bytes.",
                    )
                )

            if not hasattr(bot, "route_callback"):
                continue

            route_keyboards: list[Any] = []

            def _cap_edit(_cid: int, _mid: int, _text: str, keyboard: Any = None) -> None:
                if keyboard:
                    route_keyboards.append(keyboard)

            setattr(bot, "tg_edit", _cap_edit)
            before_unknown = seen_unknown_action
            try:
                bot.route_callback(cb, chat_id=1, msg_id=2, user_id=123, cbq_id="cbq")
            except Exception as e:
                setattr(bot, "tg_edit", _stub_edit)
                missing_handlers += 1
                _menu_qa_dev_log(f"route_crash:{cb}:{type(e).__name__}")
                issues.append(
                    QaIssue(
                        severity="warning",
                        type="missing_handler",
                        menu="routing",
                        callback=cb,
                        message=f"route_callback crashed: {e}",
                        suggested_fix="Add routing handler or guard for this callback.",
                    )
                )
                continue
            setattr(bot, "tg_edit", _stub_edit)

            if _dangerous_callback(cb) and not _allowlisted_safe(cb):
                ok_static = _has_matching_confirm_step(cb, collected_callbacks)
                ok_route = _keyboards_offer_confirm(route_keyboards)
                if not (ok_static or ok_route):
                    unsafe_actions += 1
                    _menu_qa_dev_log(f"missing_confirm:{cb}")
                    src = sorted(callback_sources.get(cb, set()))
                    issues.append(
                        QaIssue(
                            severity="warning",
                            type="unsafe_action",
                            menu="callbacks",
                            callback=cb,
                            message="Dangerous callback: no x:*yes* confirm in static menus or first routing tg_edit (heuristic).",
                            suggested_fix="Use c:* → confirm screen with x:*_yes (or x:auto:*) before any POST with confirm:true.",
                            risk=_risk_description(cb),
                            expected_confirm=_expected_confirm_hint(cb),
                            source_menus=src,
                        )
                    )

            if seen_unknown_action > before_unknown and cb not in {"m:home"}:
                missing_handlers += 1
                issues.append(
                    QaIssue(
                        severity="warning",
                        type="missing_handler",
                        menu="routing",
                        callback=cb,
                        message="Callback fell through to unknown action handler.",
                        suggested_fix="Add explicit routing case for this callback_data.",
                    )
                )
    finally:
        if callable(_orig_is_admin):
            setattr(bot, "is_admin", _orig_is_admin)

    # Overall status: never "fail" — operators see healthy vs warning only.
    render_errors = sum(1 for i in issues if i.type == "render_error")
    status = "warning" if issues else "pass"

    unsafe_callbacks_report = [
        {
            "callback": x.callback,
            "risk": x.risk or _risk_description(x.callback),
            "expected_confirm": x.expected_confirm or _expected_confirm_hint(x.callback),
            "source_menus": list(x.source_menus or []),
        }
        for x in issues
        if x.type == "unsafe_action"
    ]

    return {
        "status": status,
        "summary": {
            "menus_checked": int(menus_checked),
            "buttons_checked": int(buttons_checked),
            "callbacks_checked": int(callbacks_checked),
            "missing_handlers": int(missing_handlers),
            "missing_translations": int(missing_translations),
            "unsafe_actions": int(unsafe_actions),
            "render_errors": int(render_errors),
            "unsafe_callbacks": unsafe_callbacks_report,
        },
        "issues": [
            {
                "severity": x.severity,
                "type": x.type,
                "menu": x.menu,
                "callback": x.callback,
                "message": x.message,
                "suggested_fix": x.suggested_fix,
                "risk": x.risk or "",
                "expected_confirm": x.expected_confirm or "",
                "source_menus": list(x.source_menus or []),
            }
            for x in issues
        ],
    }

