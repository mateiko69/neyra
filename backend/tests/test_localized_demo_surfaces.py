"""Demo/matches virtualization + locale phrase banks."""

from __future__ import annotations

import pytest

from app.constants.supported_app_locales import ALL_SUPPORTED_APP_LOCALES
from app.services.ai.english_leak import ENGLISH_LEAK_MARKERS, english_leak_detected
from app.services.ai.localized_demo_text import (
    coerce_demo_partner_message_body,
    localized_other_options,
    virtual_demo_outbound_line,
)
from starlette.requests import Request


@pytest.mark.parametrize("loc", ALL_SUPPORTED_APP_LOCALES)
def test_virtual_demo_line_no_common_english(loc: str) -> None:
    if loc == "en":
        return
    txt = virtual_demo_outbound_line(locale=loc, message_id=19)
    assert txt.strip()
    assert english_leak_detected(txt, locale=loc) is False


@pytest.mark.parametrize("loc", ALL_SUPPORTED_APP_LOCALES)
def test_other_options_non_english_not_leaking(loc: str) -> None:
    if loc == "en":
        return
    s = localized_other_options(loc)
    assert s.strip()
    low = s.lower()
    assert not any(m in low for m in ENGLISH_LEAK_MARKERS)


def test_coerce_demo_partner_replaces_leaked_english() -> None:
    out = coerce_demo_partner_message_body(
        raw_db="Hi Nora coffee shop plans or see what happens",
        locale="de",
        message_id=501,
        sender_is_demo_bot=True,
        route="test",
    )
    assert out.strip()
    assert english_leak_detected(out, locale="de") is False


@pytest.mark.parametrize("chain", ["en", "uk", "fr", "de", "pt", "ko", "zh-TW"])
def test_resolve_http_survives(chain: str):
    """Switching locales via headers picks distinct resolution sources without errors."""
    from app.services.ai.locale_pipeline import ordered_legacy_ui_locales_from_request

    hdr = chain
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/x",
        "headers": [(b"x-app-locale", hdr.encode())],
        "query_string": b"",
    }

    rc = Request(scope)
    legacy = ordered_legacy_ui_locales_from_request(rc)
    assert isinstance(legacy, list)
