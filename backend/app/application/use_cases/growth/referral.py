from __future__ import annotations

from sqlalchemy.orm import Session

from app.services.growth.referral_system import ReferralSystem


def generate_referral(db: Session, user_id: int) -> dict:
    sys = ReferralSystem()
    sys.mark_referral_sent(db, user_id)
    return sys.get_referral_status(db, user_id)

