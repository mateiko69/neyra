from __future__ import annotations

from app.services.ai.cultural_tone import cultural_tone_prompt_lines, get_cultural_tone
from app.services.ai.dating_assistant_prompts import universal_dating_assistant_system
from app.services.ai.locale_rewrite import _batch_translate_prompt


def test_get_cultural_tone_ja_polite_subtle():
    t = get_cultural_tone("ja")
    assert "polite" in t.lower()
    assert "subtle" in t.lower() or "indirect" in t.lower()


def test_get_cultural_tone_es_warm_playful():
    t = get_cultural_tone("es")
    assert "warm" in t.lower()
    assert "expressive" in t.lower() or "playful" in t.lower()


def test_get_cultural_tone_ar_modest_not_pushy_flirty():
    t = get_cultural_tone("ar")
    assert "modest" in t.lower()
    assert "respectful" in t.lower()
    assert "flirty" not in t.lower()


def test_get_cultural_tone_uk_sincere():
    t = get_cultural_tone("uk")
    assert "warm" in t.lower()
    assert "sincere" in t.lower()


def test_get_cultural_tone_zh_tw_matches_zh():
    assert get_cultural_tone("zh-TW") == get_cultural_tone("zh")


def test_get_cultural_tone_default_for_unknown_primary():
    t = get_cultural_tone("xx")
    assert "natural" in t.lower()
    assert "respectful" in t.lower()


def test_universal_system_includes_cultural_block_for_ja():
    body = universal_dating_assistant_system("ja")
    assert "polite" in body.lower()
    assert "Do not stereotype" in body
    assert "Warm:" in body
    assert "1–2 short sentences" in body
    assert "question" in body.lower()


def test_universal_system_uk_language_and_tone():
    body = universal_dating_assistant_system("uk")
    assert "uk" in body
    assert "sincere" in body.lower()


def test_batch_translate_prompt_includes_tone_rules():
    system, _ = _batch_translate_prompt("ko", ["Hello?"])
    assert "ko" in system
    assert "polite" in system.lower() or "light" in system.lower()
    assert "Do not stereotype" in system


def test_cultural_tone_prompt_lines_consistency():
    block = cultural_tone_prompt_lines("tr")
    assert "tr" in block
    assert get_cultural_tone("tr").lower() in block.lower()
