"""
Shared helpers for Telegram bot production QA tests (keyboard shape, HTML safety heuristics).
"""

from __future__ import annotations

import re
from typing import Any

# Telegram Bot API message length limit (UTF-8 bytes matter on wire; char count is conservative proxy).
TELEGRAM_MESSAGE_MAX_CHARS = 4096

# Tags supported by Telegram HTML parse mode subset used by NEYRA bot (conservative allowlist).
_ALLOWED_HTML_TAGS = frozenset(
    {"b", "strong", "i", "em", "u", "ins", "s", "strike", "del", "span", "tg-spoiler", "code", "pre", "a", "br"}
)


def assert_inline_keyboard_is_rows(kb: list[list[dict[str, str]]] | None) -> None:
    assert kb is not None, "keyboard must not be None"
    assert isinstance(kb, list), "inline_keyboard must be a list of rows"
    for row in kb:
        assert isinstance(row, list), "each keyboard row must be a list"
        for btn in row:
            assert isinstance(btn, dict), "each button must be a dict"
            assert "text" in btn, "button must have text"


def collect_callback_data(kb: list[list[dict[str, str]]] | None) -> list[str]:
    assert_inline_keyboard_is_rows(kb)
    out: list[str] = []
    for row in kb:
        for btn in row:
            cb = str(btn.get("callback_data") or "").strip()
            if cb:
                out.append(cb)
    return out


def keyboard_has_nav_escape(kb: list[list[dict[str, str]]] | None) -> bool:
    """True if user can reach home, AI hub, more menu, or explicit back cancel."""
    assert_inline_keyboard_is_rows(kb)
    nav_prefixes = ("m:home", "m:ai", "m:more", "m:command_center")
    for row in kb:
        for btn in row:
            cb = str(btn.get("callback_data") or "")
            if cb.startswith(nav_prefixes):
                return True
            txt = str(btn.get("text") or "").lower()
            if "back" in txt or "назад" in txt or "🔙" in txt:
                return True
            if "cancel" in txt or "скас" in txt:
                return True
    return False


_TAG_RE = re.compile(r"<(/?)([a-zA-Z][a-zA-Z0-9:-]*)", re.ASCII)


def telegram_html_allowlist_ok(html: str) -> tuple[bool, str]:
    """
    Heuristic: reject obvious unsafe tags; allow known Telegram HTML subset openings.
    Does not fully parse HTML — complements escape() usage in the bot.
    """
    s = html or ""
    for m in _TAG_RE.finditer(s):
        closing, name = m.group(1), m.group(2).lower()
        base = name.split(":", 1)[0]
        if base not in _ALLOWED_HTML_TAGS:
            return False, f"disallowed tag: <{m.group(0)}"
    return True, ""


def telegram_html_pairs_balanced(html: str) -> tuple[bool, str]:
    """Cheap balance check for paired tags (skipped inside <pre> blocks where `<` is literal)."""
    s = html or ""
    if "<pre" in s.lower():
        return True, ""
    stack: list[str] = []

    def _push(name: str) -> None:
        stack.append(name)

    def _pop(expected: str) -> bool:
        if not stack or stack[-1] != expected:
            return False
        stack.pop()
        return True

    for m in _TAG_RE.finditer(s):
        closing, raw_name = m.group(1), m.group(2).lower()
        name = raw_name.split(":", 1)[0]
        if name not in {"b", "strong", "i", "em", "code", "pre"}:
            continue
        if name in {"b", "strong"}:
            canon = "b"
        elif name in {"i", "em"}:
            canon = "i"
        else:
            canon = name
        if closing == "/":
            if not _pop(canon):
                return False, f"unbalanced closing </{name}>"
        else:
            _push(canon)

    if stack:
        return False, f"unclosed tags: {stack}"
    return True, ""


def message_fits_telegram_limit(text: str, limit: int = TELEGRAM_MESSAGE_MAX_CHARS) -> bool:
    return len(text or "") <= limit


def split_telegram_safe_chunks(text: str, limit: int = TELEGRAM_MESSAGE_MAX_CHARS) -> list[str]:
    """Deterministic UTF-16-safe-ish chunking for Telegram length limits (tests / bot hardening)."""
    t = text or ""
    if len(t) <= limit:
        return [t]
    return [t[i : i + limit] for i in range(0, len(t), limit)]
