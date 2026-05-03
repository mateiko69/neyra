from app.services.app_language import resolve_ai_request_locale


def test_resolve_ai_request_locale_defaults_to_en():
    assert resolve_ai_request_locale(None) == "en"
    assert resolve_ai_request_locale("") == "en"


def test_resolve_ai_request_locale_uk():
    assert resolve_ai_request_locale("uk") == "uk"
    assert resolve_ai_request_locale("UA") == "uk"
