from __future__ import annotations

from sqlalchemy.orm import Session

from app.services.viral.referral_engine import ReferralEngine


def generate_referral_link(db: Session, user_id: int) -> dict:
    return ReferralEngine().generate_referral_link(db, user_id)

