"""Non-English AI/demo fallbacks must never ship common English product shells."""

from __future__ import annotations

import pytest

from app.services.ai.ai_fallback_engine import (
    copilot_suggestion_rows,
    opener_suggestion_rows,
    revive_message_rows,
    timed_reply_rows,
)
from app.services.ai.conversation.closer_meeting import closer_copilot_fallback_lines
from app.services.ai.english_leak import english_leak_detected
from app.services.ai.soft_meeting_ladder_phrases import soft_meeting_ladder_triple

NON_EN_LOCALES = (
    "ar",
    "bg",
    "cs",
    "da",
    "de",
    "el",
    "es",
    "fi",
    "fr",
    "he",
    "hi",
    "hu",
    "id",
    "it",
    "ja",
    "ko",
    "nl",
    "no",
    "pl",
    "pt",
    "ro",
    "ru",
    "sv",
    "th",
    "tr",
    "uk",
    "vi",
    "zh",
    "zh-TW",
)

CLOSER_STAGES = (
    "stalled",
    "ready_for_meeting",
    "high_interest",
    "engaged",
    "opener",
    "early_chat",
)


@pytest.mark.parametrize("loc", NON_EN_LOCALES)
def test_closer_copilot_fallback_never_triggers_english_leak_markers(loc: str) -> None:
    for cs in CLOSER_STAGES:
        lines = closer_copilot_fallback_lines(loc, cs, "", False)
        joined = "\n".join(lines)
        assert not english_leak_detected(joined, locale=loc), f"{loc} {cs}: {joined!r}"

    lines2 = closer_copilot_fallback_lines(loc, "early_chat", "How was your weekend? Tell me everything.", True)
    joined2 = "\n".join(lines2)
    assert not english_leak_detected(joined2, locale=loc), f"{loc} early_chat_continue: {joined2!r}"


@pytest.mark.parametrize("loc", NON_EN_LOCALES)
def test_soft_meeting_ladder_defined(loc: str) -> None:
    a, b, c = soft_meeting_ladder_triple(loc)
    assert a.strip() and b.strip() and c.strip()
    blob = f"{a}\n{b}\n{c}"
    assert not english_leak_detected(blob, locale=loc), blob


@pytest.mark.parametrize("loc", NON_EN_LOCALES)
def test_timed_reply_rows_localized(loc: str) -> None:
    for nudge in ("reengage", "revive", "now"):
        rows = timed_reply_rows(nudge, loc)
        joined = " ".join(str(r.get("text") or "") for r in rows)
        assert not english_leak_detected(joined, locale=loc), f"{loc} {nudge}"


@pytest.mark.parametrize("loc", NON_EN_LOCALES)
def test_copilot_suggestion_rows_with_closer_stage(loc: str) -> None:
    rows = copilot_suggestion_rows(
        loc,
        last_message="hello there",
        continue_mode=False,
        closer_stage="engaged",
    )
    joined = " ".join(str(r.get("text") or "") for r in rows)
    assert not english_leak_detected(joined, locale=loc), joined


@pytest.mark.parametrize("loc", NON_EN_LOCALES)
def test_opener_rows_not_english_marker_blob(loc: str) -> None:
    rows = opener_suggestion_rows(loc)
    joined = " ".join(str(r.get("text") or "") for r in rows)
    assert not english_leak_detected(joined, locale=loc), joined


@pytest.mark.parametrize("loc", NON_EN_LOCALES)
def test_revive_rows_localized_strings(loc: str) -> None:
    rows = revive_message_rows(loc)
    joined = "|".join(f'{r.get("label")}:{r.get("text")}' for r in rows)
    assert not english_leak_detected(joined, locale=loc), joined
    assert all(str(r.get("text") or "").strip() for r in rows)
