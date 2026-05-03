from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


StreakLevel = Literal["hot", "rising", "cold"]


@dataclass(frozen=True)
class HookLoop:
    trigger: str
    action: str
    reward: str
    investment: str

    def to_dict(self) -> dict:
        return {"trigger": self.trigger, "action": self.action, "reward": self.reward, "investment": self.investment}

