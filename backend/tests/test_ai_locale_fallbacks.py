import asyncio

from app.api.v1.endpoints.ai import _fallback_3_replies_localized, _fallback_3_replies_uk
from app.services.app_language import normalize_app_language
from app.services.ai.ai_fallback_engine import _fallback_line_has_english_leak_for_uk, sanitize_fallback_lines_for_locale
from app.services.ai.locale import is_text_locale
from app.services.ai.conversation.coach_rules import coach_intervention
from app.services.ai.conversation.last_message_signals import build_last_message_reply_context, detect_partner_intent
from app.services.ai.conversation.recovery_rules import recovery_intervention


def test_normalize_app_language_defaults_to_en_for_empty():
    assert normalize_app_language("") == "en"
    assert normalize_app_language(None) == "en"


def test_is_text_locale_rejects_cyrillic_for_en():
    assert is_text_locale("Hello, how are you?", "en") is True
    assert is_text_locale("Привіт, як справи?", "en") is False


def test_coach_rules_default_locale_is_en_not_uk():
    res = coach_intervention(messages=[{"role": "me", "text": "ok"}, {"role": "them", "text": "ok"}], draft="ok", readiness_score=30, plan_tier="premium", locale=None)
    # If locale defaults to EN, the message should be Latin-only.
    assert is_text_locale(res.message or "", "en") is True


def test_recovery_rules_default_locale_is_en_not_uk():
    res = recovery_intervention(
        messages=[{"role": "me", "text": "ok"}, {"role": "them", "text": "ok"}],
        last_message_age_minutes=24 * 60 + 10,
        readiness_score=20,
        coach_state="idle",
        plan_tier="premium_plus",
        locale=None,
    )
    assert is_text_locale(res.message or "", "en") is True


def test_fallback_3_replies_uk_has_no_english_leak_heuristic():
    for row in _fallback_3_replies_uk("Привіт", continue_mode=False):
        assert not _fallback_line_has_english_leak_for_uk(row)
    for row in _fallback_3_replies_uk("places and people mix", continue_mode=True):
        assert not _fallback_line_has_english_leak_for_uk(row)


def test_fallback_3_replies_localized_uk_async():
    opts = asyncio.run(_fallback_3_replies_localized("тест", locale="uk", continue_mode=False))
    assert len(opts) == 3
    for line in opts:
        assert not _fallback_line_has_english_leak_for_uk(line)


def test_last_message_signals_question_intent():
    assert detect_partner_intent("Ти завтра вільний?") == "question"
    ctx = build_last_message_reply_context("Привіт 🙂 розкажи, як твій день?")
    assert ctx["intent"] == "question"
    assert "tone" in ctx and "guidance_for_replies" in ctx


def test_sanitize_uk_replaces_obvious_english_lines():
    fixed = sanitize_fallback_lines_for_locale(
        ["Nice 🙂 what would you say?", "Second", "Third"],
        "uk",
        context="test",
    )
    assert len(fixed) == 3
    for line in fixed:
        assert not _fallback_line_has_english_leak_for_uk(line)

