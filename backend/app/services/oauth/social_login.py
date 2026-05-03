from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from fastapi import HTTPException

from app.core.security import create_access_token
import logging
from app.models.oauth_account import OAuthAccount
from app.models.profile import Profile
from app.services.trust.verification_state import normalize_verification_status
from app.models.user import User
from app.services.monetization.signup_trial import apply_signup_premium_trial
from app.utils.media_urls import normalize_photo_url

PROVIDER_GOOGLE = "google"
PROVIDER_APPLE = "apple"
PROVIDER_FACEBOOK = "facebook"

logger = logging.getLogger(__name__)


def _email_verified_flag(raw: bool | str | None) -> bool:
    if raw is True:
        return True
    if raw is False or raw is None:
        return False
    if isinstance(raw, str):
        return raw.lower() in ("true", "1", "yes")
    return bool(raw)


def _normalized_display_name(display_name: str | None, fallback_email: str) -> str:
    candidate = (display_name or "").strip() or fallback_email.split("@")[0]
    return candidate[:100]


def _photo_urls_list(raw: str | None) -> list[str]:
    return [part.strip() for part in (raw or "").split(",") if part.strip()]


def _preferred_age_range_complete(profile: Profile) -> bool:
    if profile.min_preferred_age is None or profile.max_preferred_age is None:
        return False
    if profile.min_preferred_age < 18 or profile.max_preferred_age > 99:
        return False
    return profile.min_preferred_age <= profile.max_preferred_age


def _profile_is_complete(profile: Profile | None) -> bool:
    if not profile:
        return False
    if not (getattr(profile, "display_name", "") or "").strip():
        return False
    # Core matching fields required before entering Discover.
    # NOTE: OAuth can prefill `display_name` + a photo, but the rest must be collected in onboarding.
    age = getattr(profile, "age", None)
    if age is None or int(age or 0) < 18:
        return False
    if not (getattr(profile, "city", "") or "").strip():
        return False
    urls = _photo_urls_list(profile.photo_urls)
    if not urls:
        return False
    if not (getattr(profile, "gender", "") or "").strip():
        return False
    if not (getattr(profile, "native_language", "") or "").strip():
        return False
    if not (getattr(profile, "interested_in", "") or "").strip():
        return False
    if not (getattr(profile, "relationship_goal", "") or "").strip():
        return False
    if not (getattr(profile, "vibe", "") or "").strip():
        return False
    if not _preferred_age_range_complete(profile):
        return False
    return True


def profile_needs_onboarding(profile: Profile | None) -> bool:
    if not profile:
        return True
    # Sticky: once completed, do not force onboarding again.
    if bool(getattr(profile, "onboarding_completed", False)):
        return False
    return not _profile_is_complete(profile)


def redirect_path_for_user(db: Session, user: User, *, is_new_user: bool) -> str:
    if is_new_user:
        return "/onboarding"
    profile = db.query(Profile).filter(Profile.user_id == user.id).first()
    if profile_needs_onboarding(profile):
        return "/onboarding"
    return "/discover"


def _ensure_social_profile(
    db: Session,
    *,
    user: User,
    email_norm: str,
    display_name: str | None,
    picture_url: str | None,
) -> tuple[Profile, bool]:
    profile = db.query(Profile).filter(Profile.user_id == user.id).first()
    changed = False
    normalized_name = _normalized_display_name(display_name, email_norm)
    normalized_picture = (picture_url or "").strip()[:8000]

    if not profile:
        profile = Profile(
            user_id=user.id,
            display_name=normalized_name,
            photo_urls=normalized_picture,
            # OAuth email verification is not the same as NEYRA selfie/profile verification.
            verified=False,
            verified_at=None,
            verification_status="none",
        )
        db.add(profile)
        return profile, True

    if not (profile.display_name or "").strip():
        profile.display_name = normalized_name
        changed = True

    if not _photo_urls_list(profile.photo_urls) and normalized_picture:
        profile.photo_urls = normalized_picture
        changed = True

    # Do not auto-award the public verified badge from OAuth.
    # The badge means `verification_status == verified` after selfie/admin verification.
    if normalize_verification_status(getattr(profile, "verification_status", None)) != "verified":
        if bool(getattr(profile, "verified", False)):
            profile.verified = False
            profile.verified_at = None
            changed = True

    if changed:
        db.add(profile)
    return profile, changed


def primary_photo_url(profile: Profile | None) -> str:
    if not profile:
        return ""
    parts = _photo_urls_list(profile.photo_urls)
    if not parts:
        return ""
    return normalize_photo_url(parts[0])


def social_account_summary(db: Session, user_id: int) -> tuple[str | None, str | None]:
    account = (
        db.query(OAuthAccount)
        .filter(OAuthAccount.user_id == user_id)
        .order_by(OAuthAccount.id.asc())
        .first()
    )
    if not account:
        return None, None
    return account.provider, account.provider_user_id


def _commit_oauth_changes(db: Session) -> None:
    logger.info("oauth_commit_before")
    try:
        db.commit()
        logger.info("oauth_commit_after")
    except IntegrityError as e:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="This social account is already linked. Refresh and try signing in again.",
        ) from e


def find_or_create_user_from_oauth(
    db: Session,
    *,
    provider: str,
    provider_user_id: str,
    email: str | None,
    email_verified: bool,
    display_name: str | None,
    picture_url: str | None,
) -> tuple[User, str, str]:
    """
    Returns (user, access_token, redirect_path).
    """
    acc = (
        db.query(OAuthAccount)
        .filter(OAuthAccount.provider == provider, OAuthAccount.provider_user_id == provider_user_id)
        .first()
    )
    if acc:
        user = db.query(User).filter(User.id == acc.user_id).first()
        if not user:
            raise HTTPException(status_code=500, detail="Account data is inconsistent.")
        email_norm = (user.email or "").strip().lower()
        profile_existing = db.query(Profile).filter(Profile.user_id == user.id).first()
        logger.info(
            "oauth_login provider=%s oauth_user_found=true email_fallback=false profile_found=%s onboarding_before=%s user_id=%s profile_id=%s",
            provider,
            bool(profile_existing),
            bool(profile_needs_onboarding(profile_existing)) if profile_existing else True,
            int(user.id),
            int(profile_existing.id) if profile_existing else None,
        )
        _profile, changed = _ensure_social_profile(
            db,
            user=user,
            email_norm=email_norm,
            display_name=display_name,
            picture_url=picture_url,
        )
        committed = False
        if changed:
            logger.info(
                "oauth_profile_update_before_commit provider=%s user_id=%s profile_id=%s",
                provider,
                int(user.id),
                int(_profile.id) if getattr(_profile, "id", None) else None,
            )
            _commit_oauth_changes(db)
            logger.info(
                "oauth_profile_update_after_commit provider=%s user_id=%s profile_id=%s",
                provider,
                int(user.id),
                int(_profile.id) if getattr(_profile, "id", None) else None,
            )
            committed = True
        logger.info(
            "oauth_profile_upsert provider=%s user_id=%s profile_found=%s profile_created=%s committed=%s committed_profile_id=%s onboarding_after=%s",
            provider,
            int(user.id),
            True,
            bool(profile_existing is None and committed),
            bool(committed),
            int(_profile.id) if getattr(_profile, "id", None) else None,
            bool(profile_needs_onboarding(_profile)),
        )
        token = create_access_token(str(user.id))
        path = redirect_path_for_user(db, user, is_new_user=False)
        return user, token, path

    if not email or not str(email).strip():
        raise HTTPException(
            status_code=400,
            detail="No email in this sign-in response. For Apple, choose “Share my email” on first sign-in, or use Google.",
        )
    if not email_verified:
        raise HTTPException(
            status_code=400,
            detail="Email from the provider is not verified. Use a verified account or email/password.",
        )

    email_norm = str(email).strip().lower()

    user = db.query(User).filter(User.email == email_norm).first()
    if user:
        profile_existing = db.query(Profile).filter(Profile.user_id == user.id).first()
        logger.info(
            "oauth_login provider=%s oauth_user_found=false email_fallback=true profile_found=%s onboarding_before=%s user_id=%s profile_id=%s",
            provider,
            bool(profile_existing),
            bool(profile_needs_onboarding(profile_existing)) if profile_existing else True,
            int(user.id),
            int(profile_existing.id) if profile_existing else None,
        )
        existing_same_provider = (
            db.query(OAuthAccount).filter(OAuthAccount.user_id == user.id, OAuthAccount.provider == provider).first()
        )
        if existing_same_provider and existing_same_provider.provider_user_id != provider_user_id:
            raise HTTPException(
                status_code=409,
                detail=f"This email already has another {provider} account linked. Use the sign-in method you started with.",
            )
        if not existing_same_provider:
            db.add(
                OAuthAccount(
                    user_id=user.id,
                    provider=provider,
                    provider_user_id=provider_user_id,
                    email_snapshot=email_norm,
                )
            )
        _profile, _changed = _ensure_social_profile(
            db,
            user=user,
            email_norm=email_norm,
            display_name=display_name,
            picture_url=picture_url,
        )
        _commit_oauth_changes(db)
        logger.info(
            "oauth_profile_upsert provider=%s user_id=%s profile_found=%s profile_created=%s committed=%s committed_profile_id=%s onboarding_after=%s",
            provider,
            int(user.id),
            True,
            bool(profile_existing is None),
            True,
            int(_profile.id) if getattr(_profile, "id", None) else None,
            bool(profile_needs_onboarding(_profile)),
        )
        token = create_access_token(str(user.id))
        path = redirect_path_for_user(db, user, is_new_user=False)
        return user, token, path

    new_user = User(
        email=email_norm,
        hashed_password=None,
        is_active=True,
        matches_last_seen_at=datetime.now(UTC),
    )
    db.add(new_user)
    db.flush()
    apply_signup_premium_trial(db, user=new_user, source=f"oauth_new:{provider}")
    logger.info("oauth_login provider=%s oauth_user_found=false email_fallback=false profile_found=false onboarding_before=true user_id=%s", provider, int(new_user.id))
    _profile, _changed = _ensure_social_profile(
        db,
        user=new_user,
        email_norm=email_norm,
        display_name=display_name,
        picture_url=picture_url,
    )
    db.add(
        OAuthAccount(
            user_id=new_user.id,
            provider=provider,
            provider_user_id=provider_user_id,
            email_snapshot=email_norm,
        )
    )
    _commit_oauth_changes(db)
    db.refresh(new_user)
    logger.info(
        "oauth_profile_upsert provider=%s user_id=%s profile_found=false profile_created=true committed=true committed_profile_id=%s onboarding_after=%s",
        provider,
        int(new_user.id),
        int(_profile.id) if getattr(_profile, "id", None) else None,
        bool(profile_needs_onboarding(_profile)),
    )
    token = create_access_token(str(new_user.id))
    path = redirect_path_for_user(db, new_user, is_new_user=True)
    return new_user, token, path


def claims_from_google(info: dict) -> tuple[str, str | None, bool, str | None, str | None]:
    sub = info.get("sub")
    if not sub:
        raise HTTPException(status_code=400, detail="Google token missing subject")
    email = info.get("email")
    ev = _email_verified_flag(info.get("email_verified"))
    name = info.get("name") or " ".join(
        x for x in (info.get("given_name"), info.get("family_name")) if x
    ).strip() or None
    picture = info.get("picture")
    return str(sub), str(email) if email else None, ev, name, str(picture) if picture else None


def claims_from_apple(info: dict) -> tuple[str, str | None, bool, str | None, str | None]:
    sub = info.get("sub")
    if not sub:
        raise HTTPException(status_code=400, detail="Apple token missing subject")
    email = info.get("email")
    ev = _email_verified_flag(info.get("email_verified")) if email else True
    return str(sub), str(email) if email else None, ev, None, None


def claims_from_facebook(profile: dict) -> tuple[str, str | None, bool, str | None, str | None]:
    sub = profile.get("id")
    if not sub:
        raise HTTPException(status_code=400, detail="Facebook profile missing id")
    email = profile.get("email")
    name = profile.get("name")
    if not email:
        raise HTTPException(
            status_code=400,
            detail="Facebook did not return an email. Grant email permission or use another sign-in method.",
        )
    picture_data = profile.get("picture") if isinstance(profile.get("picture"), dict) else {}
    picture_info = picture_data.get("data") if isinstance(picture_data.get("data"), dict) else {}
    picture_url = picture_info.get("url")
    return str(sub), str(email), True, str(name) if name else None, str(picture_url) if picture_url else None
