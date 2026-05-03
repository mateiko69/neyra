from app.core.config import settings


class AppleTokenError(Exception):
    pass


def verify_apple_id_token(token: str) -> dict:
    """Validate Apple identity token (Sign in with Apple)."""
    if not settings.ENABLE_APPLE_OAUTH or not settings.APPLE_OAUTH_CLIENT_ID:
        raise AppleTokenError("Apple sign-in is not configured")
    try:
        import jwt
        from jwt import PyJWKClient
    except ImportError as e:
        raise AppleTokenError("Apple sign-in dependencies are not available (install PyJWT).") from e
    try:
        jwks_client = PyJWKClient("https://appleid.apple.com/auth/keys")
        signing_key = jwks_client.get_signing_key_from_jwt(token)
        data = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=settings.APPLE_OAUTH_CLIENT_ID,
            issuer="https://appleid.apple.com",
        )
    except Exception as e:
        raise AppleTokenError("Invalid or expired Apple token") from e
    return data
