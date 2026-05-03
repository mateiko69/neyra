import secrets

from jose import jwt, JWTError
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.api.api_errors import api_error
from app.core.config import settings
from app.db.session import SessionLocal
from app.models.user import User
from app.services.monetization.access import MonetizationAccess

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")

_DELETED_USER_ALLOWED_PATHS = {
    # Allow a deleted user to authenticate and reach restore UX safely.
    "/api/v1/auth/me",
    "/api/v1/account/restore",
}

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def get_current_user(
    request: Request,
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    credentials_exception = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Could not validate credentials")
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
        user_id = payload.get("sub")
        if not user_id:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    user = db.query(User).filter(User.id == int(user_id)).first()
    if not user:
        raise credentials_exception
    if bool(getattr(user, "is_deleted", False)):
        path = str(getattr(request, "url", None).path if getattr(request, "url", None) else "")
        if path not in _DELETED_USER_ALLOWED_PATHS:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "ACCOUNT_DELETED",
                    "message": "Account is scheduled for deletion. Restore within 30 days to continue.",
                    "deleted_at": getattr(user, "deleted_at", None).isoformat() if getattr(user, "deleted_at", None) else None,
                    "deletion_scheduled_for": getattr(user, "deletion_scheduled_for", None).isoformat() if getattr(user, "deletion_scheduled_for", None) else None,
                },
            )
    return user

def get_admin_user(current_user: User = Depends(get_current_user)):
    if current_user.email.lower() not in settings.admin_emails_list():
        raise HTTPException(status_code=403, detail="Admin access required")
    return current_user


def get_admin_service_actor(request: Request) -> dict:
    token = str(request.headers.get("X-Admin-Service-Token") or "").strip()
    expected = str(getattr(settings, "ADMIN_BOT_SERVICE_TOKEN", "") or "").strip()
    if not token or not expected:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid service token")
    if not secrets.compare_digest(token, expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid service token")
    return {"type": "service", "name": "telegram_admin_bot"}


def require_feature(feature: str):
    """Dependency factory: 402 when the current user lacks the monetized feature."""

    def _require(
        current_user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> User:
        if not settings.ENABLE_PREMIUM_FEATURES:
            return current_user
        res = MonetizationAccess().check_access(db, int(current_user.id), feature)
        if not bool(res.get("allowed")):
            raise HTTPException(status_code=status.HTTP_402_PAYMENT_REQUIRED, detail=api_error("paywall.feature_locked", feature=feature))
        return current_user

    return _require


def get_admin_actor(
    request: Request,
    db: Session = Depends(get_db),
) -> User | dict:
    """
    Admin access for admin endpoints:
    - Either a normal admin user via Bearer JWT
    - Or a valid internal service token via X-Admin-Service-Token
    """
    if request.headers.get("X-Admin-Service-Token"):
        return get_admin_service_actor(request)

    # Manual Bearer extraction (can't use oauth2_scheme because it's not optional).
    auth = str(request.headers.get("Authorization") or "")
    if not auth.lower().startswith("bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Could not validate credentials")
    token = auth.split(" ", 1)[1].strip()
    # Reuse get_current_user logic
    user = get_current_user(request=request, token=token, db=db)
    if user.email.lower() not in settings.admin_emails_list():
        raise HTTPException(status_code=403, detail="Admin access required")
    return user
