from __future__ import annotations

from app.application.ai.conversation_ai import ConversationAI
from app.models.profile import Profile
from app.services.demo_mode import build_demo_reply


def test_demo_bot_answers_city_question_uk():
    p = Profile(display_name="Sasha", city="Kyiv", preferred_language="uk", age=24, interests="music, travel")
    out = build_demo_reply(p, "\u0442\u0438 \u0437 \u044f\u043a\u043e\u0433\u043e \u043c\u0456\u0441\u0442\u0430?", [])
    low = out.lower()
    assert "kyiv" in low or "\u043a\u0438" in low  # Kyiv/Київ/Києва variants
    assert "що для тебе" not in low


def test_demo_bot_answers_age_question_uk():
    p = Profile(display_name="Sasha", city="Kyiv", preferred_language="uk", age=24)
    out = build_demo_reply(p, "\u0441\u043a\u0456\u043b\u044c\u043a\u0438 \u0442\u043e\u0431\u0456 \u0440\u043e\u043a\u0456\u0432?", [])
    assert "24" in out
    assert "що для тебе" not in out.lower()


def test_demo_bot_answers_hobby_question_uk():
    p = Profile(display_name="Sasha", preferred_language="uk", interests="кіно, музика, кава")
    out = build_demo_reply(p, "\u044f\u043a\u0456 \u0432 \u0442\u0435\u0431\u0435 \u0445\u043e\u0431\u0456?", [])
    low = out.lower()
    assert "\u043a\u0456\u043d\u043e" in low or "\u043c\u0443\u0437" in low
    assert "що для тебе" not in low


def test_reply_suggestions_use_intent_for_city_question():
    me = Profile(display_name="Me", city="Верховина", preferred_language="uk")
    sugg = ConversationAI.reply_suggestions("\u0442\u0438 \u0437 \u044f\u043a\u043e\u0433\u043e \u043c\u0456\u0441\u0442\u0430?", me)
    assert len(sugg) >= 3
    assert any("\u0432\u0435\u0440\u0445\u043e\u0432" in (s or "").lower() for s in sugg)
    assert not any("що для тебе" in (s or "").lower() for s in sugg)

