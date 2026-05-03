"""Referral / invite helpers: stable codes, invite URLs, attribution."""

from __future__ import annotations

import secrets
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.user import User

REFERRAL_CODE_LEN = 8
# Unambiguous for sharing aloud (no 0/O, 1/I/L).
_CODE_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"


def normalize_referral_code(raw: str | None) -> str:
    if not raw:
        return ""
    return "".join(ch for ch in str(raw).strip().upper() if ch in _CODE_ALPHABET)[:16]


def generate_unique_referral_code(db: Session) -> str:
    for _ in range(64):
        code = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(REFERRAL_CODE_LEN))
        exists = db.query(User.id).filter(User.referral_code == code).first()
        if not exists:
            return code
    raise RuntimeError("referral_code_allocation_failed")


def ensure_referral_code_for_user(db: Session, user: User) -> str:
    if user.referral_code:
        return user.referral_code
    user.referral_code = generate_unique_referral_code(db)
    db.add(user)
    db.flush()
    return user.referral_code


def build_invite_link(code: str) -> str:
    base = (settings.FRONTEND_URL or "http://localhost:3000").rstrip("/")
    return f"{base}/signup?ref={code}"


def resolve_referrer_user(db: Session, code: str | None) -> User | None:
    normalized = normalize_referral_code(code)
    if len(normalized) < REFERRAL_CODE_LEN:
        return None
    return db.query(User).filter(User.referral_code == normalized).first()


def try_apply_referral_to_user(db: Session, user: User, code: str | None) -> bool:
    """Set referred_by if code is valid and not self. Does not commit. Returns True if set."""
    if user.referred_by_user_id:
        return False
    referrer = resolve_referrer_user(db, code)
    if not referrer or referrer.id == user.id:
        return False
    user.referred_by_user_id = referrer.id
    db.add(user)
    return True
