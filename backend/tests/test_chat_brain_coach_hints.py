"""Conversation-coach hints merged into chat-brain coaching payload."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.services.ai.chat_brain_suggestions import (
    _merge_coach_hints,
    _suggest_say_simple,
)


def test_suggest_say_simple_when_partner_long_message() -> None:
    ctx = {"last_text_role": "partner"}
    lines = [("partner", "word " * 30)]
    assert _suggest_say_simple(ctx, lines) is True


def test_merge_adds_premium_teaser_for_free_engaged() -> None:
    now = datetime.now(UTC)
    lines = []
    for i in range(8):
        role = "me" if i % 2 == 0 else "partner"
        lines.append((role, "Something with a bit of length here."))
    ctx = {
        "text_count": 8,
        "last_text_role": "partner",
        "last_text_at": now - timedelta(minutes=2),
        "now": now,
    }
    out = _merge_coach_hints({"action": "write_now"}, ctx, lines, "reply", "free")
    assert out.get("premium_teaser_key") == "natural"


def test_merge_no_premium_teaser_when_subscribed() -> None:
    now = datetime.now(UTC)
    lines = [("me", "hello there friend"), ("partner", "hi back to you")]
    ctx = {"text_count": 8, "last_text_role": "partner", "last_text_at": now, "now": now}
    out = _merge_coach_hints({"action": "write_now"}, ctx, lines, "reply", "premium")
    assert out.get("premium_teaser_key") is None
