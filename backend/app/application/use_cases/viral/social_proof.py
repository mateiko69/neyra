from __future__ import annotations

from sqlalchemy.orm import Session

from app.services.viral.social_proof_engine import SocialProofEngine


def get_social_proof(db: Session, user_id: int) -> list[dict]:
    return SocialProofEngine().get_signals(db, user_id)

