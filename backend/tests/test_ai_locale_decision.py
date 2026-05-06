from app.services.ai.locale_decision import detect_message_locale, resolve_ai_locale_decision


def test_detect_message_locale_ukrainian():
    assert detect_message_locale("Привіт, як справи?") == "uk"


def test_detect_message_locale_english():
    assert detect_message_locale("Hey, how are you?") == "en"


def test_detect_message_locale_russian_cyrillic():
    assert detect_message_locale("Привет как дела") == "ru"


def test_resolve_ai_locale_prefers_message_over_interface():
    loc, source = resolve_ai_locale_decision(
        latest_user_message="Привіт, як справи?",
        interface_locale="en-US",
        profile_locale="en",
    )
    assert (loc, source) == ("uk", "message")


def test_resolve_ai_locale_uses_interface_when_message_missing():
    loc, source = resolve_ai_locale_decision(
        latest_user_message="",
        interface_locale="uk-UA",
        profile_locale="en",
    )
    assert (loc, source) == ("uk", "interface")


def test_resolve_ai_locale_uses_profile_then_fallback():
    loc_profile, source_profile = resolve_ai_locale_decision(
        latest_user_message="",
        interface_locale="",
        profile_locale="ru-RU",
    )
    assert (loc_profile, source_profile) == ("ru", "profile")

    loc_fallback, source_fallback = resolve_ai_locale_decision(
        latest_user_message="",
        interface_locale="",
        profile_locale="",
    )
    assert (loc_fallback, source_fallback) == ("en", "fallback")
