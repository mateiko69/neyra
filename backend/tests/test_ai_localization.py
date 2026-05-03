from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.services.ai_localization import (
    STYLE_GUIDE,
    TARGET_LOCALE_FILES,
    TARGET_LOCALE_SET,
    TRANSLATE_UI_DIRECTIVE,
    BatchTranslationPayload,
    SingleStringQualityPayload,
    TranslationQualityResult,
    check_translation_quality,
    context_instructions,
    translate_one_key,
    translate_text,
)


def test_target_locales_are_all_non_english_supported():
    assert TARGET_LOCALE_SET == frozenset(TARGET_LOCALE_FILES)
    assert "en" not in TARGET_LOCALE_SET
    assert len(TARGET_LOCALE_FILES) == 28
    assert "zh-TW" in TARGET_LOCALE_SET
    assert "ar" in TARGET_LOCALE_SET


def test_batch_translation_payload_requires_every_target_locale():
    row = {loc: "ok" for loc in TARGET_LOCALE_FILES}
    p = BatchTranslationPayload(translations={"demo.key": row})
    assert p.translations["demo.key"]["ja"] == "ok"


def test_batch_translation_payload_rejects_missing_locale():
    row = {loc: "ok" for loc in TARGET_LOCALE_FILES if loc != "pl"}
    with pytest.raises(ValidationError):
        BatchTranslationPayload(translations={"demo.key": row})


def test_batch_translation_payload_rejects_extra_locale():
    row = {loc: "ok" for loc in TARGET_LOCALE_FILES}
    row["xx"] = "nope"
    with pytest.raises(ValidationError):
        BatchTranslationPayload(translations={"demo.key": row})


def test_style_and_directive_non_empty():
    assert "premium" in STYLE_GUIDE.lower()
    assert "dating" in TRANSLATE_UI_DIRECTIVE.lower()
    assert "robotic" in TRANSLATE_UI_DIRECTIVE.lower()


def test_context_instructions_button():
    t = context_instructions("chat.button.delete")
    assert "short" in t.lower() or "button" in t.lower()


def test_context_instructions_chat():
    t = context_instructions("chat.message.placeholder")
    assert "chat" in t.lower() or "conversational" in t.lower()


def test_context_instructions_premium():
    t = context_instructions("premium.title.upgrade")
    assert "premium" in t.lower() or "emotional" in t.lower()


def test_context_instructions_system():
    t = context_instructions("errors.api.generic")
    assert "system" in t.lower() or "clear" in t.lower()


def test_translate_one_key_requires_api(monkeypatch):
    import app.services.ai_localization as mod

    def boom(*_a, **_k):
        raise RuntimeError("no network in unit test")

    monkeypatch.setattr(mod, "_openai_responses_parse_json", boom)
    try:
        translate_one_key("x.y", "Hello")
    except RuntimeError as e:
        assert "no network" in str(e) or "OpenAI" in str(e)
    else:
        raise AssertionError("expected RuntimeError")


def test_check_translation_quality_returns_fixed(monkeypatch):
    import app.services.ai_localization as mod

    def fake_parse(system_prompt: str, user_prompt: str, model, **_kwargs):
        assert "friendly" in system_prompt.lower() or "premium" in system_prompt.lower()
        assert "uk" in user_prompt.lower()
        return SingleStringQualityPayload(fixed_text="Привіт", issues=["robotic"])

    monkeypatch.setattr(mod, "_openai_responses_parse_json", fake_parse)
    r = check_translation_quality("Hello there", "uk", reference_english="Hello there", i18n_key="chat.message.hi")
    assert isinstance(r, TranslationQualityResult)
    assert r.text == "Привіт"
    assert r.changed is True
    assert "robotic" in r.issues


def test_check_translation_quality_placeholder_guard(monkeypatch):
    import app.services.ai_localization as mod

    def fake_parse(*_a, **_k):
        return SingleStringQualityPayload(fixed_text="Hola {wrong}", issues=[])

    monkeypatch.setattr(mod, "_openai_responses_parse_json", fake_parse)
    r = check_translation_quality("Hola {name}", "es", reference_english="Hi {name}")
    assert r.changed is False
    assert "placeholder" in "".join(r.issues).lower()


def test_translate_text_same_as_translate_one_key(monkeypatch):
    import app.services.ai_localization as mod

    def boom(*_a, **_k):
        raise RuntimeError("no network in unit test")

    monkeypatch.setattr(mod, "_openai_responses_parse_json", boom)
    try:
        translate_text("k", "Hi")
    except RuntimeError:
        pass
    else:
        raise AssertionError("expected RuntimeError")
