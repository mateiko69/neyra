from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.domain.growth.config import DEFAULT_GROWTH_CONFIG, GrowthConfig
from app.models.analytics_event import AnalyticsEvent
from app.services.analytics import track_event


@dataclass(frozen=True)
class Reward:
    reward_type: str
    label: str

    def to_dict(self) -> dict:
        return {"reward_type": self.reward_type, "label": self.label}


class RewardSystem:
    """Grants small, honest rewards that reinforce healthy engagement."""

    def __init__(self, config: GrowthConfig = DEFAULT_GROWTH_CONFIG):
        self._c = config

    def grant_reward(self, db: Session, user_id: int, action: str, payload: dict | None = None) -> list[dict]:
        a = (action or "").strip()
        rewards: list[Reward] = []

        if a == "first_match":
            rewards.append(Reward("badge", "First match"))
        elif a == "first_message":
            rewards.append(Reward("badge", "First message"))
        elif a == "profile_completion":
            rewards.append(Reward("boost", "Visibility boost (24h)"))
        elif a == "successful_reply_chain":
            rewards.append(Reward("boost", "Momentum boost (12h)"))
        elif a == "conversation_streak":
            streak = int((payload or {}).get("streak_count", 0) or 0)
            if streak > 0 and streak % self._c.streak_reward_every == 0:
                rewards.append(Reward("temporary_premium", "Premium (24h)"))

        for r in rewards:
            track_event(db, "reward_granted", user_id=user_id, payload={"action": a, **r.to_dict()})

        return [r.to_dict() for r in rewards]

    def rewards_unlocked_last_day(self, db: Session, user_id: int) -> list[dict]:
        now = datetime.now(UTC)
        day_ago = now - timedelta(days=1)
        rows = (
            db.query(AnalyticsEvent)
            .filter((AnalyticsEvent.user_id == user_id) & (AnalyticsEvent.name == "reward_granted") & (AnalyticsEvent.created_at >= day_ago))
            .order_by(AnalyticsEvent.created_at.desc())
            .all()
        )
        # Keep minimal: payload is JSON string elsewhere; endpoints can query via events if needed.
        return [{"event_id": r.id, "created_at": r.created_at.isoformat()} for r in rows[:20]]

