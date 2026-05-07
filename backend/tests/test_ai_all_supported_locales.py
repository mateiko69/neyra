from __future__ import annotations

from pathlib import Path

import pytest

from app.constants.supported_app_locales import (
    ALL_SUPPORTED_APP_LOCALES,
    discover_supported_app_locale_codes,
)
from app.services.ai.ai_request_locale import normalize_ai_request_locale
from app.services.ai.ai_fallback_phrases import (
    _OPENER_TYPED,
    _TIMED_NOW_EMERGENCY,
    _TIMED_REENGAGE,
    _TIMED_REVIVE,
    demo_brain_reply_instruction,
    opener_typed_fallback,
    resolve_fallback_locale_key,
    timed_rows_for_nudge,
)
from app.services.ai.cache import cache_key
from app.services.ai.output_script_locale import text_matches_requested_locale


def _repo_locales_glob() -> set[str]:
    root = Path(__file__).resolve().parents[2]
    loc_dir = root / "frontend" / "locales"
    if not loc_dir.is_dir():
        return set(ALL_SUPPORTED_APP_LOCALES)
    return {p.stem for p in loc_dir.glob("*.json")}


def test_all_supported_app_locales_matches_frontend_glob():
    assert set(ALL_SUPPORTED_APP_LOCALES) == _repo_locales_glob()
    assert len(ALL_SUPPORTED_APP_LOCALES) >= 1


def test_discover_supported_app_locale_codes_is_sorted_tuple():
    codes = discover_supported_app_locale_codes()
    assert isinstance(codes, tuple)
    assert list(codes) == sorted(codes)


@pytest.mark.parametrize("ui_locale", list(ALL_SUPPORTED_APP_LOCALES))
def test_phrase_bank_rows_exist_for_every_locale(ui_locale: str):
    key = resolve_fallback_locale_key(ui_locale)
    assert key in _OPENER_TYPED, ui_locale
    assert key in _TIMED_REENGAGE
    assert key in _TIMED_REVIVE
    assert key in _TIMED_NOW_EMERGENCY


@pytest.mark.parametrize("ui_locale", [x for x in ALL_SUPPORTED_APP_LOCALES if x != "en"])
def test_opener_fallback_text_not_english_template(ui_locale: str):
    rows = opener_typed_fallback(ui_locale)
    joined = " ".join(t for _, t in rows)
    en_joined = " ".join(t for _, t in opener_typed_fallback("en"))
    assert joined != en_joined, ui_locale
    # Japanese/Korean lines mix kana/hangul with ideographs; mixed-script heuristic is too strict.
    if normalize_ai_request_locale(ui_locale) not in {"ja", "ko"}:
        assert text_matches_requested_locale(joined, ui_locale), (ui_locale, joined[:120])


@pytest.mark.parametrize("ui_locale", [x for x in ALL_SUPPORTED_APP_LOCALES if x != "en"])
def test_timed_reengage_fallback_not_english_template(ui_locale: str):
    opts, loc = timed_rows_for_nudge("reengage", ui_locale)
    joined = " ".join(o.get("text") or "" for o in opts)
    assert loc == normalize_ai_request_locale(ui_locale)
    en_joined = " ".join(o.get("text") or "" for o in timed_rows_for_nudge("reengage", "en")[0])
    assert joined != en_joined, ui_locale
    if normalize_ai_request_locale(ui_locale) not in {"ja", "ko"}:
        assert text_matches_requested_locale(joined, ui_locale), (ui_locale, joined[:120])


@pytest.mark.parametrize("ui_locale", [x for x in ALL_SUPPORTED_APP_LOCALES if x != "en"])
def test_demo_brain_footer_not_literal_english(ui_locale: str):
    foot = demo_brain_reply_instruction(ui_locale)
    assert "Never mention AI or demo" not in foot


def test_gemini_cache_key_varies_with_locale_hint():
    base_prompt = "You are NEYRA.\nLANGUAGE: en\nSay hello."
    p_en = {
        "provider": "gemini",
        "model": "m",
        "prompt": base_prompt.replace("LANGUAGE: en", "LANGUAGE: en"),
        "generation": {},
        "locale_hint": "en",
        "surface": "openers",
    }
    p_pt = dict(p_en)
    p_pt["prompt"] = base_prompt.replace("LANGUAGE: en", "LANGUAGE: pt")
    p_pt["locale_hint"] = "pt"
    assert cache_key("gemini_prompt_v1", p_en) != cache_key("gemini_prompt_v1", p_pt)
