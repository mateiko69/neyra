from __future__ import annotations

from app.services.demo_mode import _catalog_gender_to_profile_gender


def test_catalog_gender_prefers_gender_profile_over_legacy_gender() -> None:
    assert (
        _catalog_gender_to_profile_gender({"gender_profile": "man", "gender": "female"}) == "man"
    )
    assert (
        _catalog_gender_to_profile_gender({"gender_profile": "woman", "gender": "male"}) == "woman"
    )


def test_catalog_gender_accepts_legacy_female_male() -> None:
    assert _catalog_gender_to_profile_gender({"gender": "female"}) == "woman"
    assert _catalog_gender_to_profile_gender({"gender": "male"}) == "man"


def test_catalog_gender_accepts_woman_man_in_gender_field() -> None:
    assert _catalog_gender_to_profile_gender({"gender": "woman"}) == "woman"
    assert _catalog_gender_to_profile_gender({"gender": "man"}) == "man"


def test_catalog_gender_fallback_woman() -> None:
    assert _catalog_gender_to_profile_gender({}) == "woman"
