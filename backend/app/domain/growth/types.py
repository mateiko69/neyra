from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


ActivityLevel = Literal["low", "medium", "high"]
Priority = Literal["low", "medium", "high"]
Channel = Literal["push", "in_app"]


@dataclass(frozen=True)
class EngagementState:
    activity_level: ActivityLevel
    last_active_hours: float
    matches_recent: int
    messages_sent: int
    reply_rate: float
    drop_risk: int

    def to_dict(self) -> dict:
        return {
            "activity_level": self.activity_level,
            "last_active_hours": self.last_active_hours,
            "matches_recent": self.matches_recent,
            "messages_sent": self.messages_sent,
            "reply_rate": self.reply_rate,
            "drop_risk": self.drop_risk,
        }

