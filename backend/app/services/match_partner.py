"""Match checks for partner-only features (chat, public profile view)."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.match import Match
from app.services.safety import is_blocked


def users_are_matched(db: Session, user_a: int, user_b: int) -> bool:
    if is_blocked(db, user_a, user_b):
        return False
    a, b = sorted([user_a, user_b])
    return db.query(Match).filter(Match.user_a_id == a, Match.user_b_id == b).first() is not None
