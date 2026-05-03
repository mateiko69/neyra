from __future__ import annotations

from sqlalchemy.orm import Session

from app.services.monetization.paywalls import PaywallTrigger


def trigger_paywall(db: Session, user_id: int, context: dict) -> dict:
    return PaywallTrigger().trigger_paywall(db, user_id, context)

