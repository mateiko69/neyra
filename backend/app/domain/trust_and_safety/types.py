from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


Severity = Literal["low", "medium", "high"]
SafetyAction = Literal[
    "allow",
    "allow_with_warning",
    "allow_with_rewrite_suggestion",
    "soft_block",
    "hard_block",
    "shadow_downrank",
    "require_review",
]


@dataclass(frozen=True)
class MessageRiskResult:
    allowed: bool
    risk_score: int
    flags: list[str]
    quality_flags: list[str]
    rewrite_suggestion: str | None

    def to_dict(self) -> dict:
        out = {
            "allowed": self.allowed,
            "risk_score": self.risk_score,
            "flags": self.flags,
            "quality_flags": self.quality_flags,
        }
        if self.rewrite_suggestion:
            out["rewrite_suggestion"] = self.rewrite_suggestion
        return out


@dataclass(frozen=True)
class ProfileRiskResult:
    risk_score: int
    flags: list[str]
    quality_score: int
    recommended_actions: list[str]

    def to_dict(self) -> dict:
        return {
            "risk_score": self.risk_score,
            "flags": self.flags,
            "quality_score": self.quality_score,
            "recommended_actions": self.recommended_actions,
        }


@dataclass(frozen=True)
class ScamSignalsResult:
    scam_risk: int
    signals: list[str]
    severity: Severity

    def to_dict(self) -> dict:
        return {"scam_risk": self.scam_risk, "signals": self.signals, "severity": self.severity}


@dataclass(frozen=True)
class BotSignalsResult:
    bot_probability: int
    signals: list[str]

    def to_dict(self) -> dict:
        return {"bot_probability": self.bot_probability, "signals": self.signals}

