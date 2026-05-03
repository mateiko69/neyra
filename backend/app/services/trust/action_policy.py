from __future__ import annotations

from dataclasses import dataclass

from app.domain.matching.utils import clamp_int
from app.domain.trust_and_safety.config import DEFAULT_THRESHOLDS, Thresholds
from app.domain.trust_and_safety.types import SafetyAction


@dataclass(frozen=True)
class PolicyInput:
    message_risk: int = 0
    profile_risk: int = 0
    bot_probability: int = 0
    scam_risk: int = 0
    conversation_quality: int = 70


class ActionPolicy:
    """Explainable policy engine combining multiple signals."""

    def __init__(self, thresholds: Thresholds = DEFAULT_THRESHOLDS):
        self._t = thresholds

    def decide(self, inp: PolicyInput) -> tuple[SafetyAction, list[str]]:
        reasons: list[str] = []

        msg = clamp_int(inp.message_risk)
        profile = clamp_int(inp.profile_risk)
        bot = clamp_int(inp.bot_probability)
        scam = clamp_int(inp.scam_risk)
        quality = clamp_int(inp.conversation_quality)

        if msg >= self._t.hard_block_message_risk or scam >= 90:
            reasons.append("high_message_or_scam_risk")
            return "hard_block", reasons

        if msg >= self._t.soft_block_message_risk or scam >= self._t.possible_scam_risk:
            reasons.append("elevated_message_or_scam_risk")
            return "soft_block", reasons

        if bot >= self._t.possible_bot_probability:
            reasons.append("possible_bot")
            return "require_review", reasons

        if profile >= self._t.require_review_profile_risk:
            reasons.append("high_profile_risk")
            return "require_review", reasons

        if profile >= self._t.downrank_profile_risk:
            reasons.append("downrank_profile_risk")
            # Keep browsing usable; downrank is not a block.
            return "shadow_downrank", reasons

        if msg >= self._t.rewrite_message_risk and quality < 55:
            reasons.append("low_quality_message_rewrite")
            return "allow_with_rewrite_suggestion", reasons

        if msg >= self._t.warn_message_risk:
            reasons.append("message_warning")
            return "allow_with_warning", reasons

        return "allow", reasons

