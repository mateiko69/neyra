from __future__ import annotations

import pytest

from app.models.profile import Profile
from app.schemas.profile import ProfilePatch
from app.services.oauth.social_login import _profile_is_complete


def _base_profile() -> Profile:
    return Profile(
        user_id=1,
        display_name="Test",
        photo_urls="https://example.com/a.jpg",
        age=24,
        city="Kyiv",
        gender="woman",
        native_language="uk",
        additional_languages="en,ru",
        relationship_goal="dating",
        vibe="warm",
        interested_in="men",
        min_preferred_age=22,
        max_preferred_age=35,
    )


def test_profile_is_complete_requires_all_matching_fields_and_photo():
    p = _base_profile()
    assert _profile_is_complete(p) is True

    p2 = _base_profile()
    p2.photo_urls = ""
    assert _profile_is_complete(p2) is False

    p3 = _base_profile()
    p3.city = ""
    assert _profile_is_complete(p3) is False

    p4 = _base_profile()
    p4.age = None
    assert _profile_is_complete(p4) is False

    p5 = _base_profile()
    p5.age = 17
    assert _profile_is_complete(p5) is False

    p6 = _base_profile()
    p6.native_language = ""
    assert _profile_is_complete(p6) is False

    p7 = _base_profile()
    p7.relationship_goal = ""
    assert _profile_is_complete(p7) is False

    p7b = _base_profile()
    p7b.vibe = ""
    assert _profile_is_complete(p7b) is False

    p8 = _base_profile()
    p8.interested_in = ""
    assert _profile_is_complete(p8) is False

    p9 = _base_profile()
    p9.min_preferred_age = 30
    p9.max_preferred_age = 20
    assert _profile_is_complete(p9) is False


def test_profile_patch_validates_under_18_and_partner_age_range():
    with pytest.raises(Exception):
        ProfilePatch.model_validate({"age": 17})

    with pytest.raises(Exception):
        ProfilePatch.model_validate({"partner_age_min": 35, "partner_age_max": 20})

    # Cap at 80 (older UI sometimes sent 99).
    with pytest.raises(Exception):
        ProfilePatch.model_validate({"max_preferred_age": 99})

    with pytest.raises(Exception):
        ProfilePatch.model_validate({"partner_age_max": 99})

