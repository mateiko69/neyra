from __future__ import annotations

from sqlalchemy.orm import Session

from app.services.viral.streak_engine import StreakEngine


def get_streak(db: Session, user_id: int) -> dict:
    return StreakEngine().get_daily_open_streak(db, user_id)

