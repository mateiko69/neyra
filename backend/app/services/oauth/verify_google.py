from app.core.config import settings


class GoogleTokenError(Exception):
    pass


def verify_google_id_token(token: str) -> dict:
    """Validate Google ID token; return claims (sub, email, email_verified, name, picture, …)."""
    if not settings.ENABLE_GOOGLE_OAUTH or not settings.GOOGLE_OAUTH_CLIENT_ID:
        raise GoogleTokenError("Google sign-in is not configured")
    try:
        from google.auth.transport import requests as google_requests
        from google.oauth2 import id_token
    except ImportError as e:
        raise GoogleTokenError(
            "Google sign-in dependencies are not available (install google-auth and requests)."
        ) from e
    try:
        info = id_token.verify_oauth2_token(token, google_requests.Request(), settings.GOOGLE_OAUTH_CLIENT_ID)
    except Exception as e:
        raise GoogleTokenError("Invalid or expired Google token") from e
    iss = info.get("iss")
    if iss not in ("accounts.google.com", "https://accounts.google.com"):
        raise GoogleTokenError("Invalid Google token issuer")
    return info
