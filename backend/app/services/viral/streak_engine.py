from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.domain.viral.config import DEFAULT_VIRAL_CONFIG, ViralConfig
from app.models.analytics_event import AnalyticsEvent


class StreakEngine:
    """Tracks daily streak based on real events (no faking).

    Uses `user_returned` (already tracked by growth engagement endpoint) as the daily open signal.
    """

    def __init__(self, config: ViralConfig = DEFAULT_VIRAL_CONFIG):
        self._c = config

    def get_daily_open_streak(self, db: Session, user_id: int) -> dict:
        now = datetime.now(UTC)
        window = now - timedelta(days=60)
        rows = (
            db.query(AnalyticsEvent)
            .filter((AnalyticsEvent.user_id == user_id) & (AnalyticsEvent.name == "user_returned") & (AnalyticsEvent.created_at >= window))
            .order_by(AnalyticsEvent.created_at.desc())
            .all()
        )
        days = {r.created_at.date() for r in rows}
        streak = 0
        d = now.date()
        while d in days:
            streak += 1
            d = d - timedelta(days=1)

        level = "cold"
        if streak >= self._c.streak_hot_days:
            level = "hot"
        elif streak >= self._c.streak_rising_days:
            level = "rising"

        return {"streak_days": streak, "streak_level": level}

