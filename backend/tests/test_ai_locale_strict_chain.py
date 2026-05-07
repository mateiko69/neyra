"""Strict AI locale chain: body → profile → Accept-Language → UI headers → en."""

from __future__ import annotations

import pytest

from app.services.ai.locale_pipeline import resolve_ai_locale_strict_chain


@pytest.mark.parametrize(
    "req,prof,accept,transport,expected_lang,expected_src",
    [
        ("pt", "", "", "", "pt", "request_body"),
        ("", "fr", "", "", "fr", "profile"),
        ("", "", "pt-BR,en;q=0.9", "", "pt", "accept_language"),
        ("", "", "", "de", "de", "ui_header"),
        ("", "", "", "", "en", "fallback_en"),
        ("zh-CN", "", "", "", "zh", "request_body"),
    ],
)
def test_resolve_ai_locale_strict_chain_order(
    req: str,
    prof: str,
    accept: str,
    transport: str,
    expected_lang: str,
    expected_src: str,
) -> None:
    loc, src = resolve_ai_locale_strict_chain(
        req_locale=req or None,
        profile_locale=prof or None,
        accept_language_header=accept or None,
        transport_locale=transport or None,
    )
    assert loc == expected_lang
    assert src == expected_src


def test_pt_matches_ui_when_headers_only() -> None:
    """Portuguese UI often arrives via X-Locale after body/profile empty."""
    loc, src = resolve_ai_locale_strict_chain(
        req_locale=None,
        profile_locale=None,
        accept_language_header=None,
        transport_locale="pt",
    )
    assert loc == "pt"
    assert src == "ui_header"


def test_ar_from_accept_language() -> None:
    loc, src = resolve_ai_locale_strict_chain(
        req_locale=None,
        profile_locale=None,
        accept_language_header="ar, en;q=0.8",
        transport_locale=None,
    )
    assert loc == "ar"
    assert src == "accept_language"
