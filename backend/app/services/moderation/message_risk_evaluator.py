from __future__ import annotations

import re

from app.domain.ai.safety import SafetyPolicy
from app.domain.matching.utils import clamp_int
from app.domain.trust_and_safety.config import (
    CRINGE_PHRASES,
    EXPLICIT_PHRASES,
    GENERIC_SPAM_OPENERS,
    HARASSMENT_PHRASES,
    SCAM_PHRASES,
    SUSPICIOUS_BIO_PHRASES,
)
from app.domain.trust_and_safety.types import MessageRiskResult


class MessageRiskEvaluator:
    """Message-level risk + quality evaluator.

    Not everything gets blocked:
    - severe safety => blocked
    - cringe/awkward => rewrite suggestion
    - mild risk => allow with warning
    """

    @classmethod
    def evaluate_message_risk(cls, message: str, conversation_context: list[str] | None = None, *, allow_edgy_mode: bool = False) -> MessageRiskResult:
        msg = (message or "").strip()
        m = msg.lower()
        ctx = [c.strip() for c in (conversation_context or []) if (c or "").strip()]
        ctx_l = [c.lower() for c in ctx]

        flags: list[str] = []
        quality_flags: list[str] = []
        risk = 0
        rewrite: str | None = None

        # Reuse existing SafetyPolicy (harassment/manipulation/explicit + generic baseline)
        safety_flags = SafetyPolicy.validate(msg, allow_edgy_mode=allow_edgy_mode)
        if "harassment" in safety_flags:
            flags.append("harassment")
            risk += 95
        if "manipulation" in safety_flags:
            flags.append("manipulation")
            risk += 65
        if "explicit_content" in safety_flags:
            flags.append("explicit_content")
            risk += 95
        if "generic_message" in safety_flags:
            quality_flags.append("generic_opener")
            risk += 18

        if any(p in m for p in HARASSMENT_PHRASES):
            flags.append("harassment")
            risk += 95

        if not allow_edgy_mode and any(p in m for p in EXPLICIT_PHRASES):
            flags.append("explicit_content")
            risk += 95

        # Scam-like patterns
        if any(p in m for p in SUSPICIOUS_BIO_PHRASES):
            flags.append("offplatform_push")
            risk += 35
        if any(p in m for p in SCAM_PHRASES):
            flags.append("money_talk")
            risk += 35
        if re.search(r"\b(send|pay)\b.*\b(now|today|asap)\b", m):
            flags.append("payment_pressure")
            risk += 30

        # Spam / copy-paste: exact repetition in recent context
        if ctx_l and m in ctx_l[-8:]:
            quality_flags.append("repeated_message")
            risk += 22

        # Low-quality: one-liners / generic openers
        if m in GENERIC_SPAM_OPENERS:
            quality_flags.append("generic_opener")
            risk += 22

        # Cringe heuristics (non-malicious)
        if any(p in m for p in CRINGE_PHRASES):
            quality_flags.append("cringe_line")
            risk += 25

        # Aggression marker (lightweight)
        if "!!!" in msg or msg.isupper() and len(msg) >= 8:
            flags.append("aggressive_tone")
            risk += 18

        risk_score = clamp_int(risk)

        # Rewrite suggestions for recoverable quality issues
        if "cringe_line" in quality_flags:
            rewrite = "Краще без пафосу. Спробуй простіше: «Мені зайшов твій профіль. Що з твого дня було найцікавішим?»"
        elif risk_score >= 55 and risk_score < 90:
            if "generic_opener" in quality_flags:
                rewrite = "Замість банального — зачепись за деталь: «Бачу в тебе {інтерес}. Як ти в це втягуєшся?»"
            elif "aggressive_tone" in flags:
                rewrite = "Це може звучати різко. Спробуй м’якше: «Слухай, мені реально цікаво — розкажеш більше?»"

        allowed = risk_score < 75 and ("harassment" not in flags) and ("explicit_content" not in flags)

        return MessageRiskResult(
            allowed=allowed,
            risk_score=risk_score,
            flags=sorted(set(flags)),
            quality_flags=sorted(set(quality_flags)),
            rewrite_suggestion=rewrite,
        )

