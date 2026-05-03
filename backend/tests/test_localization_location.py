from __future__ import annotations

from app.services.localization.location import (
    choose_preposition,
    format_location,
    get_city_locative,
    normalize_location,
)


def test_uk_city_locative_examples():
    kyiv = normalize_location(city="Kyiv", country_code="UA")
    assert get_city_locative(kyiv, "uk") == "Києві"
    assert format_location(kyiv, "UA", "uk") == "у Києві"

    lviv = normalize_location(city="Lviv", country_code="UA")
    assert get_city_locative(lviv, "uk") == "Львові"
    assert format_location(lviv, "UA", "uk") == "у Львові"

    verk = normalize_location(city="Verkhovyna", country_code="UA")
    assert get_city_locative(verk, "uk") == "Верховині"
    assert format_location(verk, "UA", "uk") == "у Верховині"

    ch = normalize_location(city="Chernivtsi", country_code="UA")
    assert get_city_locative(ch, "uk") == "Чернівцях"
    assert format_location(ch, "UA", "uk") == "у Чернівцях"


def test_en_city_display():
    kyiv = normalize_location(city="Kyiv", country_code="UA")
    assert choose_preposition("en") == "in"
    assert format_location(kyiv, "UA", "en").startswith("in Kyiv")

