"""Accept-Language parsing + locale priority helpers."""

from __future__ import annotations

from app.services.app_language import locale_from_accept_language_header


def test_accept_language_prefers_first_non_english() -> None:
    assert locale_from_accept_language_header("en-US, uk;q=0.9") == "uk"


def test_accept_language_uk_first() -> None:
    assert locale_from_accept_language_header("uk, en;q=0.8") == "uk"


def test_accept_language_fr_from_region() -> None:
    assert locale_from_accept_language_header("fr-FR, en;q=0.9") == "fr"


def test_accept_language_empty() -> None:
    assert locale_from_accept_language_header("") == ""
    assert locale_from_accept_language_header(None) == ""
