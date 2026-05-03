from datetime import UTC, datetime

from sqlalchemy.orm import Session
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from app.api.api_errors import api_error
from app.api.deps import get_db, get_current_user
from app.core.config import settings
from app.core.security import create_access_token, get_password_hash, verify_password
from app.models.profile import Profile
from app.models.user import User
from app.services.oauth.social_login import (
    primary_photo_url,
    profile_needs_onboarding,
    social_account_summary,
)
from app.schemas.auth import AuthMeResponse, RegisterIn, LoginIn, TokenOut
from app.services.analytics import track_event
from app.services.premium import has_premium_access
from app.services.referral_rewards import sync_referral_rewards_for_inviter
from app.services.referrals import ensure_referral_code_for_user, try_apply_referral_to_user
from app.services.email_verification import issue_email_verification_token, send_verification_email, verify_email_token
from app.services.monetization.signup_trial import apply_signup_premium_trial

router = APIRouter()


def _normalize_preferred_language(raw: str | None) -> str | None:
    """
    Best-effort normalization to UI-supported locale codes.
    Mirrors frontend behavior (29 locales, plus common aliases).
    """
    if not raw:
        return None
    v = str(raw).strip().replace("_", "-")
    if not v:
        return None
    lower = v.lower()
    alias = {
        "zh-cn": "zh",
        "zh-hans": "zh",
        "zh-sg": "zh",
        "zh-tw": "zh-TW",
        "zh-hant": "zh-TW",
        "zh-hk": "zh-TW",
        "zh-mo": "zh-TW",
        "pt-br": "pt",
        "pt-pt": "pt",
        "en-us": "en",
        "en-gb": "en",
        "iw": "he",
        "nb": "no",
        "nn": "no",
    }
    if lower in alias:
        return alias[lower]
    if lower == "zh":
        return "zh"
    if lower.startswith("zh-"):
        return "zh-TW" if any(x in lower for x in ["tw", "hant", "hk", "mo"]) else "zh"
    primary = lower.split("-")[0]
    supported = {
        "en",
        "uk",
        "ru",
        "es",
        "pt",
        "fr",
        "de",
        "it",
        "pl",
        "tr",
        "zh",
        "zh-TW",
        "ja",
        "ko",
        "hi",
        "id",
        "vi",
        "th",
        "ar",
        "he",
        "bg",
        "nl",
        "sv",
        "cs",
        "ro",
        "hu",
        "el",
        "da",
        "fi",
        "no",
    }
    if v in supported:
        return v
    if primary in supported:
        return primary
    return None


def _preferred_language_from_accept_language(header_value: str | None) -> str | None:
    if not header_value:
        return None
    # take the first tag before ";q=" (keep it simple + robust)
    first = str(header_value).split(",")[0].split(";")[0].strip()
    return _normalize_preferred_language(first)


@router.post("/register", response_model=TokenOut)
def register(payload: RegisterIn, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    existing = db.query(User).filter(User.email == payload.email).first()
    if existing:
        raise HTTPException(status_code=400, detail=api_error("auth.email_taken"))
    user = User(
        email=payload.email,
        hashed_password=get_password_hash(payload.password),
        is_active=True,
        matches_last_seen_at=datetime.now(UTC),
    )
    db.add(user)
    db.flush()
    apply_signup_premium_trial(db, user=user, source="email_register")
    db.add(Profile(user_id=user.id, display_name=payload.display_name))
    ensure_referral_code_for_user(db, user)
    referred = try_apply_referral_to_user(db, user, payload.referral_code)
    if referred and user.referred_by_user_id:
        inviter = db.query(User).filter(User.id == int(user.referred_by_user_id)).first()
        if inviter:
            sync_referral_rewards_for_inviter(db, inviter, source="auto")
    db.commit()
    db.refresh(user)
    # Email verification (dev-only sender logs link). Social sign-ins can mark verified separately.
    try:
        token = issue_email_verification_token(db, user=user)
        # Fire-and-forget: if email service is not configured, registration should still succeed.
        background_tasks.add_task(send_verification_email, email=user.email, token=token)
    except Exception:
        pass
    if referred:
        track_event(db, "referral_signup_completed", user_id=user.id, payload={"source": "email_register"})
    return TokenOut(access_token=create_access_token(str(user.id)))

@router.post("/login", response_model=TokenOut)
def login(payload: LoginIn, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == payload.email).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=api_error("auth.invalid_credentials"))
    if user.hashed_password is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=api_error("auth.social_only"),
        )
    if not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=api_error("auth.invalid_credentials"))
    token = create_access_token(str(user.id))
    if bool(getattr(user, "is_deleted", False)):
        return TokenOut(
            access_token=token,
            is_deleted=True,
            deleted_at=getattr(user, "deleted_at", None).isoformat() if getattr(user, "deleted_at", None) else None,
            deletion_scheduled_for=getattr(user, "deletion_scheduled_for", None).isoformat() if getattr(user, "deletion_scheduled_for", None) else None,
        )
    return TokenOut(access_token=token)

@router.get("/me", response_model=AuthMeResponse)
async def me(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    profile = db.query(Profile).filter(Profile.user_id == current_user.id).first()
    # If user has no preferred_language yet, set it ONCE (best-effort) from Accept-Language.
    try:
        if profile and not (getattr(profile, "preferred_language", "") or "").strip():
            accept = request.headers.get("accept-language")
            detected = _preferred_language_from_accept_language(accept)
            if detected:
                profile.preferred_language = detected
                db.add(profile)
                db.commit()
                db.refresh(profile)
    except Exception:
        # Never block /auth/me on language persistence.
        pass
    email_l = current_user.email.lower()
    is_admin = email_l in settings.admin_emails_list()
    social_provider, social_provider_id = social_account_summary(db, current_user.id)
    is_premium = has_premium_access(db, current_user.id, "unlimited_ai_suggestions")
    premium_until = getattr(current_user, "premium_until", None)
    is_trial_used = bool(getattr(current_user, "is_trial_used", False)) or bool(getattr(current_user, "is_trial", False))
    trial_started_at = getattr(current_user, "trial_started_at", None)
    premium_until_iso = premium_until.isoformat() if premium_until else None
    trial_days_left = None
    if premium_until:
        try:
            until = premium_until
            if getattr(until, "tzinfo", None) is None:
                until = until.replace(tzinfo=UTC)
            now = datetime.now(UTC)
            remaining_s = (until - now).total_seconds()
            if remaining_s > 0:
                trial_days_left = int((remaining_s + 86399) // 86400)  # ceil days
        except Exception:
            trial_days_left = None
    return {
        "user_id": current_user.id,
        "email": current_user.email,
        "display_name": profile.display_name if profile else "",
        "email_verified": bool(getattr(current_user, "email_verified", False)),
        "onboarding_completed": bool(getattr(profile, "onboarding_completed", False)) if profile else False,
        "is_admin": is_admin,
        "is_premium": bool(is_premium),
        "premium_until": premium_until_iso,
        "is_trial_used": is_trial_used,
        "trial_started_at": trial_started_at.isoformat() if trial_started_at else None,
        "trial_days_left": trial_days_left,
        "verified": bool(getattr(profile, "verified", False)) if profile else False,
        "avatar_url": primary_photo_url(profile),
        "social_provider": social_provider,
        "social_provider_id": social_provider_id,
        "onboarding_required": profile_needs_onboarding(profile),
        "founder_welcome_seen": bool(getattr(profile, "founder_welcome_seen", False)) if profile else False,
        "founder_welcome_required": bool(
            profile
            and not profile_needs_onboarding(profile)
            and bool(getattr(profile, "onboarding_completed", False))
            and not bool(getattr(profile, "founder_welcome_seen", False))
        ),
        "is_deleted": bool(getattr(current_user, "is_deleted", False)),
        "deleted_at": getattr(current_user, "deleted_at", None).isoformat() if getattr(current_user, "deleted_at", None) else None,
        "deletion_scheduled_for": getattr(current_user, "deletion_scheduled_for", None).isoformat() if getattr(current_user, "deletion_scheduled_for", None) else None,
    }


@router.post("/verify-email")
def verify_email(payload: dict, db: Session = Depends(get_db)):
    token = str((payload or {}).get("token") or "").strip()
    user = verify_email_token(db, token=token)
    if not user:
        raise HTTPException(status_code=400, detail=api_error("auth.verify.invalid_or_expired"))
    access_token = create_access_token(str(user.id))
    return {"ok": True, "email_verified": True, "access_token": access_token, "token_type": "bearer"}


@router.post("/verify-email/resend")
async def resend_verify_email(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if bool(getattr(current_user, "email_verified", False)):
        return {"ok": True, "email_verified": True}
    token = issue_email_verification_token(db, user=current_user)
    send_verification_email(email=current_user.email, token=token)
    return {"ok": True, "email_verified": False}
