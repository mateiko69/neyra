"""Scripted first-five demo bot messages."""

from __future__ import annotations

from app.services.demo_bot_script import scripted_demo_message


def test_scripted_arc_has_question_and_stays_short() -> None:
    pers = {
        "personality": "warm",
        "interests": ["coffee", "travel"],
        "flirt_level": 1,
        "humor_style": "warm",
    }
    for step in range(5):
        line = scripted_demo_message(step=step, pers=pers, lang="en", partner_name="Alex")
        assert len(line) <= 220
        assert "Alex" in line or step >= 0
        assert "?" in line or "？" in line


def test_sarcastic_personality_distinct() -> None:
    pers = {"personality": "sarcastic", "interests": ["music"], "flirt_level": 0}
    a = scripted_demo_message(step=0, pers=pers, lang="en", partner_name="Sam")
    b = scripted_demo_message(step=0, pers={**pers, "personality": "warm"}, lang="en", partner_name="Sam")
    assert a != b
