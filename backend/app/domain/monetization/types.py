from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


PlanCode = Literal["free", "premium", "premium_plus"]
OfferType = Literal["trial", "subscription", "discount", "comeback"]

PremiumFeature = Literal[
    "ai_unlimited_replies",
    "ai_conversation_analysis",
    "see_who_liked_you",
    "profile_boost",
    "advanced_match_insights",
    "likes_priority_high_match",
    "ai_timing_decision",
    "meeting_readiness",
    "chat_revive_advanced",
    "priority_in_discover",
    "can_reopen_chat",
]

PaywallContext = Literal[
    "first_match",
    "reply_suggestion_request",
    "conversation_dying",
    "profile_boost_request",
    "good_match",
    "chat_started",
    "engaged_user",
]


@dataclass(frozen=True)
class AccessResult:
    allowed: bool
    reason: str
    upgrade_required: bool

    def to_dict(self) -> dict:
        return {"allowed": self.allowed, "reason": self.reason, "upgrade_required": self.upgrade_required}


@dataclass(frozen=True)
class PaywallDecision:
    show: bool
    message: str
    offer_type: OfferType

    def to_dict(self) -> dict:
        return {"show": self.show, "message": self.message, "offer_type": self.offer_type}

