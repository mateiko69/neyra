from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


EnergyLevel = Literal["low", "medium", "high"]


@dataclass(frozen=True)
class ConversationAnalysis:
    """Heuristic analysis of a conversation (0..100 metrics)."""

    interest_level: int
    response_quality: int
    risk_of_drop: int
    energy_level: EnergyLevel
    flags: list[str]

    def to_dict(self) -> dict:
        return {
            "interest_level": self.interest_level,
            "response_quality": self.response_quality,
            "risk_of_drop": self.risk_of_drop,
            "energy_level": self.energy_level,
            "flags": self.flags,
        }

