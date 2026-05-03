from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.email_verification_token import EmailVerificationToken
from app.models.user import User
from app.services.email_sender import get_email_sender


def _hash_token(token: str) -> str:
    key = (settings.SECRET_KEY or "change-me").encode("utf-8")
    raw = token.encode("utf-8")
    return hashlib.sha256(key + b":" + raw).hexdigest()


def _token_ttl() -> timedelta:
    return timedelta(hours=24)


def issue_email_verification_token(db: Session, *, user: User) -> str:
    token = secrets.token_urlsafe(32)
    now = datetime.now(UTC)
    row = EmailVerificationToken(
        user_id=int(user.id),
        token_hash=_hash_token(token),
        created_at=now,
        expires_at=now + _token_ttl(),
        used_at=None,
    )
    db.add(row)
    db.commit()
    return token


def send_verification_email(*, email: str, token: str) -> None:
    frontend = (settings.FRONTEND_URL or "").rstrip("/")
    link = f"{frontend}/verify-email?token={token}"
    subject = "Verify your email"
    body = f"Verify your email for NEYRA:\n\n{link}\n\nThis link expires in 24 hours."
    sender = get_email_sender()
    sender.send(to_email=email, subject=subject, text=body)


def verify_email_token(db: Session, *, token: str) -> User | None:
    token = (token or "").strip()
    if not token:
        return None
    h = _hash_token(token)
    now = datetime.now(UTC)
    row = (
        db.query(EmailVerificationToken)
        .filter(EmailVerificationToken.token_hash == h)
        .order_by(EmailVerificationToken.id.desc())
        .first()
    )
    if not row:
        return None
    if row.used_at is not None:
        return None
    expires = row.expires_at
    if getattr(expires, "tzinfo", None) is None:
        expires = expires.replace(tzinfo=UTC)
    if expires < now:
        return None
    user = db.query(User).filter(User.id == int(row.user_id)).first()
    if not user:
        return None
    if not bool(getattr(user, "email_verified", False)):
        user.email_verified = True
        user.email_verified_at = now
    row.used_at = now
    db.add(user)
    db.add(row)
    db.commit()
    db.refresh(user)
    return user

