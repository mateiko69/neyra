"""Topic brain + premium chat-brain context limits."""

from __future__ import annotations

from app.services.ai.chat_brain_suggestions import _normalize_conversation_mode, _transcript_limit
from app.services.ai.topic_brain import (
    TOPIC_CONFIDENCE_LOW_THRESHOLD,
    brain_line_quality_fail,
    detect_conversation_topic,
    topic_context_for_prompt,
    topic_fallback_variant,
)


def test_transcript_limit_premium_uses_longer_context() -> None:
    assert _transcript_limit("free") == 3
    assert _transcript_limit("premium") == 50
    assert _transcript_limit("premium_plus") == 50


def test_topic_travel_from_keywords() -> None:
    lines = [("partner", "I want to travel to Italy next summer")]
    meta = detect_conversation_topic(lines)
    assert meta["topic"] == "travel"
    assert meta["confidence"] >= 0.35


def test_topic_movies_from_keywords() -> None:
    lines = [("me", "hey"), ("partner", "I binge netflix series every weekend")]
    meta = detect_conversation_topic(lines)
    assert meta["topic"] == "movies"


def test_pickup_master_downgrades_for_free_plan() -> None:
    assert _normalize_conversation_mode("premium_pickup_master", "free") == "easy"
    assert _normalize_conversation_mode("premium_pickup_master", "premium") == "premium_pickup_master"


def test_free_plan_conversation_mode_is_always_easy() -> None:
    assert _normalize_conversation_mode("flirty", "free") == "easy"
    assert _normalize_conversation_mode("deep", "free") == "easy"


def test_quality_filter_blocks_generic_hobbies_prompt() -> None:
    assert (
        brain_line_quality_fail(
            "Tell me more about your hobbies",
            variant="light",
            recent_lines=[],
        )
        == "generic"
    )


def test_quality_filter_blocks_creepy_pressure() -> None:
    assert (
        brain_line_quality_fail(
            "send me a photo tonight",
            variant="flirty",
            recent_lines=[],
        )
        == "creepy"
    )


def test_topic_fallback_nonempty() -> None:
    t = topic_fallback_variant("travel", "light", "en")
    assert len(t) > 10


def test_topic_fallback_light_uses_opener_pool() -> None:
    t = topic_fallback_variant("movies", "light", "en")
    openers = __import__("app.services.ai.topic_brain", fromlist=["TOPIC_SEEDS"]).TOPIC_SEEDS["movies"]["opener"]
    assert t in openers


def test_low_confidence_prompt_includes_recovery_mode() -> None:
    meta = {"topic": "movies", "confidence": 0.3, "conversation_stage": "icebreaker", "emotional_tone": "neutral"}
    block = topic_context_for_prompt(meta, "en")
    assert "LOW_TOPIC_CONFIDENCE_MODE" in block
    assert TOPIC_CONFIDENCE_LOW_THRESHOLD > 0.3


def test_high_confidence_prompt_has_no_recovery_banner() -> None:
    meta = {"topic": "movies", "confidence": 0.9, "conversation_stage": "warming", "emotional_tone": "playful"}
    block = topic_context_for_prompt(meta, "en")
    assert "LOW_TOPIC_CONFIDENCE_MODE" not in block


def test_duplicate_line_detected() -> None:
    assert (
        brain_line_quality_fail(
            "Same exact phrase",
            variant="deep",
            recent_lines=["Same exact phrase"],
        )
        == "duplicate"
    )
