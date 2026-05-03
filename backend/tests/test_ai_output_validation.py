"""AI output validation rules (chat brain + improve-reply)."""

from __future__ import annotations

from app.services.ai.ai_output_validation import (
    pack_question_quota_met,
    sentence_count,
    validate_chat_brain_line,
    validate_improve_reply_line,
)


def test_sentence_count_two_max() -> None:
    assert sentence_count("Hi. How are you?") == 2
    assert sentence_count("One") == 1
    assert sentence_count("A. B. C.") == 3


def test_rejects_generic_and_long() -> None:
    r = validate_chat_brain_line(
        "What are your hobbies?",
        variant="light",
        recent_lines=[],
        lang="en",
        salt="t:1",
    )
    assert r == "generic"
    r2 = validate_chat_brain_line(
        "Short? " + "word " * 80,
        variant="light",
        recent_lines=[],
        lang="en",
        salt="t:2",
    )
    assert r2 == "too_long"


def test_pack_question_quota() -> None:
    assert not pack_question_quota_met({"light": "a", "flirty": "b", "deep": "c?"})
    assert pack_question_quota_met({"light": "a?", "flirty": "b?", "deep": "c"})


def test_improve_reply_validation() -> None:
    assert (
        validate_improve_reply_line(
            "Sounds good.",
            lang="en",
            index=0,
            peer_texts=[],
            salt="x",
        )
        == "no_hook"
    )
    assert (
        validate_improve_reply_line(
            "What part feels most true for you?",
            lang="en",
            index=0,
            peer_texts=[],
            salt="x",
        )
        is None
    )
