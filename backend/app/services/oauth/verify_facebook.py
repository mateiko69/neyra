from app.core.config import settings


class FacebookTokenError(Exception):
    pass


def verify_facebook_access_token(access_token: str) -> dict:
    """Validate Facebook user access token and return id, email, name, picture."""
    if not settings.ENABLE_FACEBOOK_OAUTH or not settings.FACEBOOK_APP_ID or not settings.FACEBOOK_APP_SECRET:
        raise FacebookTokenError("Facebook sign-in is not configured")
    try:
        import httpx
    except ImportError as e:
        raise FacebookTokenError("Facebook sign-in dependencies are not available (install httpx).") from e
    app_token = f"{settings.FACEBOOK_APP_ID}|{settings.FACEBOOK_APP_SECRET}"
    with httpx.Client(timeout=10.0) as client:
        dbg = client.get(
            "https://graph.facebook.com/debug_token",
            params={"input_token": access_token, "access_token": app_token},
        )
        dbg.raise_for_status()
        body = dbg.json()
        data = body.get("data") or {}
        if not data.get("is_valid"):
            raise FacebookTokenError("Invalid Facebook token")
        if str(data.get("app_id")) != str(settings.FACEBOOK_APP_ID):
            raise FacebookTokenError("Facebook token is for a different app")

        me = client.get(
            "https://graph.facebook.com/me",
            params={"fields": "id,email,name,picture.width(512).height(512)", "access_token": access_token},
        )
        me.raise_for_status()
        profile = me.json()
    if not profile.get("id"):
        raise FacebookTokenError("Facebook did not return a user id")
    return profile
