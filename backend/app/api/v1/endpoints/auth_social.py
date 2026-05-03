from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.core.config import settings
from app.schemas.social_auth import AppleTokenIn, FacebookTokenIn, GoogleTokenIn, SocialAuthOut
from app.services.oauth.social_login import (
    PROVIDER_APPLE,
    PROVIDER_FACEBOOK,
    PROVIDER_GOOGLE,
    claims_from_apple,
    claims_from_facebook,
    claims_from_google,
    find_or_create_user_from_oauth,
)
from app.services.analytics import track_event

router = APIRouter()

_STATE_TTL_SECONDS = 10 * 60


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("utf-8").rstrip("=")


def _b64url_decode(text: str) -> bytes:
    padded = text + "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(padded.encode("utf-8"))


def _sign_state(payload: dict) -> str:
    body = _b64url_encode(json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
    sig = hmac.new(settings.SECRET_KEY.encode("utf-8"), body.encode("utf-8"), hashlib.sha256).digest()
    return f"{body}.{_b64url_encode(sig)}"


def _verify_state(state: str) -> dict:
    try:
        body, sig = state.split(".", 1)
        expected = hmac.new(settings.SECRET_KEY.encode("utf-8"), body.encode("utf-8"), hashlib.sha256).digest()
        got = _b64url_decode(sig)
        if not hmac.compare_digest(expected, got):
            raise ValueError("bad signature")
        payload = json.loads(_b64url_decode(body).decode("utf-8"))
        ts = int(payload.get("ts") or 0)
        if ts <= 0 or int(time.time()) - ts > _STATE_TTL_SECONDS:
            raise ValueError("expired")
        return payload
    except Exception as e:
        raise HTTPException(status_code=400, detail="Invalid OAuth state.") from e


def _safe_next_path(raw: str | None) -> str:
    value = (raw or "").strip()
    if not value:
        return ""
    if not value.startswith("/"):
        return ""
    if value.startswith("//"):
        return ""
    return value[:500]


@router.get("/social/providers")
def social_providers():
    """Feature flags + public OAuth client ids (safe to expose)."""
    env = (settings.ENV or "").strip().lower()
    dev_mock = bool(settings.AUTH_DEV_SOCIAL) and env not in ("production", "prod")

    def missing_for_google() -> list[str]:
        missing: list[str] = []
        if not settings.ENABLE_GOOGLE_OAUTH:
            missing.append("ENABLE_GOOGLE_OAUTH")
        if not settings.GOOGLE_OAUTH_CLIENT_ID:
            missing.append("GOOGLE_OAUTH_CLIENT_ID")
        # Optional but recommended for production OAuth readiness docs.
        if not settings.GOOGLE_OAUTH_CLIENT_SECRET:
            missing.append("GOOGLE_OAUTH_CLIENT_SECRET")
        if not settings.GOOGLE_OAUTH_REDIRECT_URI:
            missing.append("GOOGLE_OAUTH_REDIRECT_URI")
        return missing

    def missing_for_apple() -> list[str]:
        missing: list[str] = []
        if not settings.ENABLE_APPLE_OAUTH:
            missing.append("ENABLE_APPLE_OAUTH")
        if not settings.APPLE_OAUTH_CLIENT_ID:
            missing.append("APPLE_OAUTH_CLIENT_ID")
        if not settings.APPLE_TEAM_ID:
            missing.append("APPLE_TEAM_ID")
        if not settings.APPLE_KEY_ID:
            missing.append("APPLE_KEY_ID")
        if not settings.APPLE_PRIVATE_KEY:
            missing.append("APPLE_PRIVATE_KEY")
        if not settings.APPLE_REDIRECT_URI:
            missing.append("APPLE_REDIRECT_URI")
        return missing

    def missing_for_facebook() -> list[str]:
        missing: list[str] = []
        if not settings.ENABLE_FACEBOOK_OAUTH:
            missing.append("ENABLE_FACEBOOK_OAUTH")
        if not settings.FACEBOOK_APP_ID:
            missing.append("FACEBOOK_APP_ID")
        if not settings.FACEBOOK_APP_SECRET:
            missing.append("FACEBOOK_APP_SECRET")
        if not settings.FACEBOOK_REDIRECT_URI:
            missing.append("FACEBOOK_REDIRECT_URI")
        return missing

    google_missing = missing_for_google()
    apple_missing = missing_for_apple()
    facebook_missing = missing_for_facebook()

    # Google "auth code" flow requires client_secret + redirect_uri (backend callback URL).
    g_on = (
        settings.ENABLE_GOOGLE_OAUTH
        and not google_missing
    )
    a_on = len([k for k in apple_missing if k != "APPLE_TEAM_ID" and k != "APPLE_KEY_ID" and k != "APPLE_PRIVATE_KEY" and k != "APPLE_REDIRECT_URI"]) == 0 and settings.ENABLE_APPLE_OAUTH
    f_on = len([k for k in facebook_missing if k != "FACEBOOK_REDIRECT_URI"]) == 0 and settings.ENABLE_FACEBOOK_OAUTH
    return {
        # Backwards-compatible booleans consumed by existing frontend.
        "google": bool(g_on),
        "apple": bool(a_on),
        "facebook": bool(f_on),
        "google_client_id": settings.GOOGLE_OAUTH_CLIENT_ID if g_on else "",
        "apple_client_id": settings.APPLE_OAUTH_CLIENT_ID if a_on else "",
        "facebook_app_id": settings.FACEBOOK_APP_ID if f_on else "",
        "dev_mock": dev_mock,
        # New structured diagnostics (no secrets returned).
        "providers": {
            "google": {"provider": "google", "enabled": bool(g_on), "missing_config_keys": google_missing},
            "apple": {"provider": "apple", "enabled": bool(a_on), "missing_config_keys": apple_missing},
            "facebook": {"provider": "facebook", "enabled": bool(f_on), "missing_config_keys": facebook_missing},
        },
    }


def _ensure_dev_mock_enabled():
    env = (settings.ENV or "").strip().lower()
    if env in ("production", "prod") or not settings.AUTH_DEV_SOCIAL:
        raise HTTPException(status_code=404, detail="Not found")


@router.post("/social/dev/{provider}", response_model=SocialAuthOut)
def social_dev(provider: str, db: Session = Depends(get_db)):
    """Dev-only mock social login to unblock UX testing without real OAuth credentials."""
    _ensure_dev_mock_enabled()
    p = (provider or "").strip().lower()
    if p not in {"google", "apple", "facebook"}:
        raise HTTPException(status_code=404, detail="Not found")
    # Stable dev identities per provider.
    provider_map = {
        "google": (PROVIDER_GOOGLE, "dev-google", "dev_google@example.com", "Dev Google"),
        "apple": (PROVIDER_APPLE, "dev-apple", "dev_apple@example.com", "Dev Apple"),
        "facebook": (PROVIDER_FACEBOOK, "dev-facebook", "dev_facebook@example.com", "Dev Facebook"),
    }
    provider_id, provider_user_id, email, display_name = provider_map[p]
    _user, token, path = find_or_create_user_from_oauth(
        db,
        provider=provider_id,
        provider_user_id=provider_user_id,
        email=email,
        email_verified=True,
        display_name=display_name,
        picture_url=None,
    )
    return SocialAuthOut(access_token=token, redirect_path=path)


@router.post("/social/google", response_model=SocialAuthOut)
def social_google(payload: GoogleTokenIn, db: Session = Depends(get_db)):
    if not (settings.ENABLE_GOOGLE_OAUTH and settings.GOOGLE_OAUTH_CLIENT_ID):
        raise HTTPException(status_code=503, detail="Google sign-in is not enabled.")
    # Lazy import so missing optional deps never run at app startup.
    from app.services.oauth.verify_google import GoogleTokenError, verify_google_id_token

    try:
        info = verify_google_id_token(payload.id_token)
    except GoogleTokenError as e:
        raise HTTPException(status_code=401, detail=str(e)) from e
    sub, email, ev, name, pic = claims_from_google(info)
    _user, token, path = find_or_create_user_from_oauth(
        db,
        provider=PROVIDER_GOOGLE,
        provider_user_id=sub,
        email=email,
        email_verified=ev,
        display_name=name,
        picture_url=pic,
    )
    return SocialAuthOut(access_token=token, redirect_path=path)


@router.get("/social/google/start")
def social_google_start(request: Request, next: str | None = None):
    """
    Start Google OAuth (authorization code flow).
    Redirects user-agent to Google consent page with a signed state payload.
    """
    if not (
        settings.ENABLE_GOOGLE_OAUTH
        and settings.GOOGLE_OAUTH_CLIENT_ID
        and settings.GOOGLE_OAUTH_CLIENT_SECRET
        and settings.GOOGLE_OAUTH_REDIRECT_URI
    ):
        raise HTTPException(status_code=503, detail="Google sign-in is not configured.")

    state = _sign_state(
        {
            "ts": int(time.time()),
            "nonce": _b64url_encode(hashlib.sha256(f"{time.time()}:{request.client.host if request.client else ''}".encode("utf-8")).digest())[:24],
            "next": _safe_next_path(next),
        }
    )
    params = {
        "client_id": settings.GOOGLE_OAUTH_CLIENT_ID,
        "redirect_uri": settings.GOOGLE_OAUTH_REDIRECT_URI,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "access_type": "online",
        "prompt": "select_account",
    }
    url = f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}"
    return RedirectResponse(url=url, status_code=302)


@router.get("/social/google/callback")
def social_google_callback(
    db: Session = Depends(get_db),
    *,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    error_description: str | None = None,
):
    """
    Google OAuth callback: validate state, exchange code, fetch userinfo, login/link user,
    then redirect to frontend callback handler.
    """
    # Always validate state before using any "next" values.
    state_payload = _verify_state(state or "")
    next_path = _safe_next_path(state_payload.get("next"))

    if error:
        # Safe, no secrets. Send user back to login.
        detail = (error_description or error).strip()[:300]
        public_frontend = str(getattr(settings, "PUBLIC_FRONTEND_URL", "") or settings.FRONTEND_URL).rstrip("/")
        target = f"{public_frontend}/login#social_error=google&reason={_b64url_encode(detail.encode('utf-8'))}"
        return RedirectResponse(url=target, status_code=302)

    if not code or not str(code).strip():
        public_frontend = str(getattr(settings, "PUBLIC_FRONTEND_URL", "") or settings.FRONTEND_URL).rstrip("/")
        target = f"{public_frontend}/login#social_error=google"
        return RedirectResponse(url=target, status_code=302)

    if not (
        settings.ENABLE_GOOGLE_OAUTH
        and settings.GOOGLE_OAUTH_CLIENT_ID
        and settings.GOOGLE_OAUTH_CLIENT_SECRET
        and settings.GOOGLE_OAUTH_REDIRECT_URI
    ):
        public_frontend = str(getattr(settings, "PUBLIC_FRONTEND_URL", "") or settings.FRONTEND_URL).rstrip("/")
        target = f"{public_frontend}/login#social_error=google"
        return RedirectResponse(url=target, status_code=302)

    # Lazy import: httpx is in requirements, but keep startup clean.
    import httpx

    try:
        with httpx.Client(timeout=10.0) as client:
            token_resp = client.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "code": code,
                    "client_id": settings.GOOGLE_OAUTH_CLIENT_ID,
                    "client_secret": settings.GOOGLE_OAUTH_CLIENT_SECRET,
                    "redirect_uri": settings.GOOGLE_OAUTH_REDIRECT_URI,
                    "grant_type": "authorization_code",
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            token_resp.raise_for_status()
            token_body = token_resp.json() if token_resp.content else {}
            access_token = str(token_body.get("access_token") or "").strip()
            if not access_token:
                raise RuntimeError("Missing access_token")

            info_resp = client.get(
                "https://openidconnect.googleapis.com/v1/userinfo",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            info_resp.raise_for_status()
            info = info_resp.json() if info_resp.content else {}
    except Exception:
        public_frontend = str(getattr(settings, "PUBLIC_FRONTEND_URL", "") or settings.FRONTEND_URL).rstrip("/")
        target = f"{public_frontend}/login#social_error=google"
        return RedirectResponse(url=target, status_code=302)

    try:
        sub, email, ev, name, pic = claims_from_google(info)
        _user, neyra_token, default_path = find_or_create_user_from_oauth(
            db,
            provider=PROVIDER_GOOGLE,
            provider_user_id=sub,
            email=email,
            email_verified=ev,
            display_name=name,
            picture_url=pic,
        )
        # Conversion analytics (safe: no secrets, no content).
        track_event(db, "social_login_success", user_id=_user.id, payload={"provider": "google"})
    except HTTPException:
        public_frontend = str(getattr(settings, "PUBLIC_FRONTEND_URL", "") or settings.FRONTEND_URL).rstrip("/")
        target = f"{public_frontend}/login#social_error=google"
        return RedirectResponse(url=target, status_code=302)

    # Do not allow `next` to skip onboarding. If backend decides onboarding is required,
    # always route to `/onboarding` regardless of the original next path.
    if (default_path or "").strip() == "/onboarding":
        redirect_path = "/onboarding"
    else:
        redirect_path = next_path or default_path or "/discover"
    fragment = urlencode({"access_token": neyra_token, "redirect_path": redirect_path})
    public_frontend = str(getattr(settings, "PUBLIC_FRONTEND_URL", "") or settings.FRONTEND_URL).rstrip("/")
    target = f"{public_frontend}/auth/social/callback#{fragment}"
    return RedirectResponse(url=target, status_code=302)


@router.post("/social/apple", response_model=SocialAuthOut)
def social_apple(payload: AppleTokenIn, db: Session = Depends(get_db)):
    if not (settings.ENABLE_APPLE_OAUTH and settings.APPLE_OAUTH_CLIENT_ID):
        raise HTTPException(status_code=503, detail="Apple sign-in is not enabled.")
    from app.services.oauth.verify_apple import AppleTokenError, verify_apple_id_token

    try:
        info = verify_apple_id_token(payload.id_token)
    except AppleTokenError as e:
        raise HTTPException(status_code=401, detail=str(e)) from e
    sub, email, ev, name, pic = claims_from_apple(info)
    fallback_name = " ".join(
        part.strip()
        for part in (payload.first_name or "", payload.last_name or "")
        if part and part.strip()
    ).strip() or None
    _user, token, path = find_or_create_user_from_oauth(
        db,
        provider=PROVIDER_APPLE,
        provider_user_id=sub,
        email=email,
        email_verified=ev,
        display_name=name or fallback_name,
        picture_url=pic,
    )
    return SocialAuthOut(access_token=token, redirect_path=path)


@router.post("/social/facebook", response_model=SocialAuthOut)
def social_facebook(payload: FacebookTokenIn, db: Session = Depends(get_db)):
    if not (settings.ENABLE_FACEBOOK_OAUTH and settings.FACEBOOK_APP_ID and settings.FACEBOOK_APP_SECRET):
        raise HTTPException(status_code=503, detail="Facebook sign-in is not enabled yet.")
    from app.services.oauth.verify_facebook import FacebookTokenError, verify_facebook_access_token

    try:
        profile = verify_facebook_access_token(payload.access_token)
    except FacebookTokenError as e:
        raise HTTPException(status_code=401, detail=str(e)) from e
    sub, email, ev, name, pic = claims_from_facebook(profile)
    _user, token, path = find_or_create_user_from_oauth(
        db,
        provider=PROVIDER_FACEBOOK,
        provider_user_id=sub,
        email=email,
        email_verified=ev,
        display_name=name,
        picture_url=pic,
    )
    return SocialAuthOut(access_token=token, redirect_path=path)
