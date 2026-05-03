from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.base import Base
from app.models.oauth_account import OAuthAccount
from app.models.profile import Profile
from app.services.oauth.social_login import (
    PROVIDER_GOOGLE,
    claims_from_facebook,
    find_or_create_user_from_oauth,
    profile_needs_onboarding,
    social_account_summary,
)


def _memory_db() -> Session:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return Session(engine)


def test_profile_needs_onboarding_allows_optional_bio_when_social_fields_are_ready():
    profile = SimpleNamespace(
        display_name="Ava",
        photo_urls="https://cdn.example.com/avatar.jpg",
        gender="woman",
        interested_in="men",
        min_preferred_age=26,
        max_preferred_age=36,
        bio="",
    )

    # As of matching-field onboarding, OAuth-prefilled fields are not enough for Discover.
    assert profile_needs_onboarding(profile) is True


def test_claims_from_facebook_extracts_picture_url():
    sub, email, verified, name, picture = claims_from_facebook(
        {
            "id": "fb_123",
            "email": "ava@example.com",
            "name": "Ava Lane",
            "picture": {"data": {"url": "https://graph.example.com/picture.jpg"}},
        }
    )

    assert sub == "fb_123"
    assert email == "ava@example.com"
    assert verified is True
    assert name == "Ava Lane"
    assert picture == "https://graph.example.com/picture.jpg"


def test_find_or_create_user_from_oauth_links_provider_without_public_verified_badge():
    db = _memory_db()

    try:
        user, _token, redirect_path = find_or_create_user_from_oauth(
            db,
            provider=PROVIDER_GOOGLE,
            provider_user_id="google-sub-1",
            email="ava@example.com",
            email_verified=True,
            display_name="Ava Lane",
            picture_url="https://cdn.example.com/ava.jpg",
        )

        profile = db.query(Profile).filter(Profile.user_id == user.id).first()
        oauth = db.query(OAuthAccount).filter(OAuthAccount.user_id == user.id).first()

        assert redirect_path == "/onboarding"
        assert profile is not None
        assert profile.display_name == "Ava Lane"
        assert profile.photo_urls == "https://cdn.example.com/ava.jpg"
        # OAuth email verification is not the same as NEYRA public selfie verification.
        assert profile.verified is False
        assert profile.verified_at is None
        assert profile.verification_status == "none"
        assert oauth is not None
        assert social_account_summary(db, user.id) == ("google", "google-sub-1")
    finally:
        db.close()
