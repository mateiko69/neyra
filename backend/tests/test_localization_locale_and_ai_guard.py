from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.services.localization.detect import detect_user_locale
from app.services.localization.locale import is_rtl_locale, normalize_locale
from app.services.ai.ai_request_locale import normalize_ai_request_locale
from app.services.ai.providers.openai_provider import _inject_locale_guard


def test_normalize_locale_extended():
    assert normalize_locale("uk-UA") == "uk"
    assert normalize_locale("ru_RU") == "ru"
    assert normalize_locale("es-ES") == "es"
    assert normalize_locale("zh-Hant") == "zh-TW"
    assert normalize_locale("zh-Hans") == "zh"
    assert normalize_locale("iw") == "he"
    assert normalize_locale(None) == "en"


def test_normalize_ai_request_locale_matches_extended_codes():
    """AI paths must use the same canonical codes as the app (zh-TW preserved, not collapsed to zh)."""
    assert normalize_ai_request_locale("zh-TW") == "zh-TW"
    assert normalize_ai_request_locale("ZH-tw") == "zh-TW"
    assert normalize_ai_request_locale("ar-SA") == "ar"
    assert normalize_ai_request_locale("he-IL") == "he"
    assert normalize_ai_request_locale("ja-JP") == "ja"
    assert normalize_ai_request_locale("de-DE") == "de"
    assert normalize_ai_request_locale("uk-UA") == "uk"
    assert normalize_ai_request_locale("") == "en"


def test_rtl_locales():
    assert is_rtl_locale("ar") is True
    assert is_rtl_locale("he") is True
    assert is_rtl_locale("en") is False


def test_detect_user_locale_priority_accept_language():
    app = FastAPI()

    @app.get("/x")
    def x():
        return {"ok": True}

    client = TestClient(app)
    req = client.build_request("GET", "/x", headers={"Accept-Language": "es-ES,uk;q=0.8,en;q=0.7"})
    # We must call detect_user_locale with a Request object; TestClient builds one internally,
    # so we instead validate normalize_locale behavior and priority logic using a real request.
    # Build a request by running a route and inspecting the server-side Request.
    captured = {}

    @app.get("/capture")
    def capture(request: Request):
        captured["locale"] = detect_user_locale(request)
        return {"locale": captured["locale"]}

    res = client.get("/capture", headers={"Accept-Language": "es-ES,uk;q=0.8,en;q=0.7"})
    assert res.json()["locale"] == "es"


def test_ai_guard_uses_locale_code_not_language_names():
    prompt = _inject_locale_guard("SYSTEM", "uk")
    assert "uk" in prompt
    assert "Do not mix languages" in prompt
    assert "Do not stereotype" in prompt
    assert "Ukrainian" not in prompt

