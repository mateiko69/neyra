from __future__ import annotations

from sqlalchemy.orm import Session

from app.services.monetization.paywall_engine import PaywallEngine


def trigger_paywall(db: Session, user_id: int, context: dict) -> dict:
    return PaywallEngine().trigger_paywall(db, user_id, context).to_dict()

