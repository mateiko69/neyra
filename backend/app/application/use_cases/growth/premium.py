from __future__ import annotations

from sqlalchemy.orm import Session

from app.services.monetization.premium_engine import PremiumEngine


def check_feature_access(db: Session, user_id: int, feature: str) -> dict:
    return PremiumEngine().check_feature_access(db, user_id, feature)

