from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.domain.growth.config import DEFAULT_GROWTH_CONFIG, GrowthConfig
from app.domain.growth.types import EngagementState
from app.models.analytics_event import AnalyticsEvent


@dataclass(frozen=True)
class Nudge:
    nudge_text: str
    nudge_type: str
    priority: str

    def to_dict(self) -> dict:
        return {"nudge_text": self.nudge_text, "nudge_type": self.nudge_type, "priority": self.priority}


class NudgeSystem:
    """Generates in-app nudges (non-spammy behavior triggers)."""

    def __init__(self, config: GrowthConfig = DEFAULT_GROWTH_CONFIG):
        self._c = config

    def generate_nudges(self, db: Session, user_id: int, engagement: EngagementState) -> list[dict]:
        # Frequency guard using analytics events.
        now = datetime.now(UTC)
        since_day = now - timedelta(days=1)
        shown_recent = (
            db.query(AnalyticsEvent)
            .filter((AnalyticsEvent.user_id == user_id) & (AnalyticsEvent.name == "nudge_shown") & (AnalyticsEvent.created_at >= since_day))
            .count()
        )
        if shown_recent >= self._c.max_nudges_per_day:
            return []

        nudges: list[Nudge] = []

        if engagement.activity_level == "low" and engagement.last_active_hours >= self._c.inactive_hours_low:
            nudges.append(Nudge("You have new potential matches", "inactive_user", "high"))
            nudges.append(Nudge("Want three openers that fit your style?", "wingman_help", "medium"))

        if engagement.matches_recent >= 3 and engagement.messages_sent == 0:
            nudges.append(Nudge("No first message yet — say hi, it takes 2 seconds.", "no_first_message", "high"))

        if engagement.reply_rate < 40 and engagement.messages_sent >= 6:
            nudges.append(Nudge("Try a different message — a new angle often works.", "no_reply", "medium"))

        # Always keep nudges short and human.
        return [n.to_dict() for n in nudges[:3]]

