"""Strict AI locale chain: body > X-App-Locale > UI headers (ordered) > Accept-Language > profile > en."""

from __future__ import annotations

import pytest

from app.services.ai.locale_pipeline import resolve_ai_locale_strict_chain


@pytest.mark.parametrize(
    "req,app,legacy,prof,accept,expected_lang,expected_src",
    [
        ("pt", "", "", "", "", "pt", "request_body"),
        ("fr", "de", "", "", "", "fr", "request_body"),
        ("", "de", "", "uk", "es", "de", "x_app_locale"),
        ("", "", "pt", "", "", "pt", "ui_header"),
        ("", "", "", "pl", "es", "es", "accept_language"),
        ("", "", "", "pl", "", "pl", "profile"),
        ("", "", "", "", "pt-BR,en;q=0.9", "pt", "accept_language"),
        ("", "", "", "", "", "en", "fallback_en"),
        ("zh-CN", "", "", "", "", "zh", "request_body"),
    ],
)
def test_resolve_ai_locale_strict_chain_order(req, app, legacy, prof, accept, expected_lang, expected_src) -> None:
    legacy_list = [legacy] if legacy else []
    loc, src = resolve_ai_locale_strict_chain(
        request_locale=req or None,
        app_locale_header=app or None,
        legacy_ui_candidates=legacy_list,
        accept_language_header=accept or None,
        profile_locale=prof or None,
    )
    assert loc == expected_lang
    assert src == expected_src


def test_ar_from_accept_language() -> None:
    loc, src = resolve_ai_locale_strict_chain(
        request_locale=None,
        app_locale_header=None,
        legacy_ui_candidates=[],
        accept_language_header="ar, en;q=0.8",
        profile_locale=None,
    )
    assert loc == "ar"
    assert src == "accept_language"
