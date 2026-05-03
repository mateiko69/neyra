from __future__ import annotations

import re

from app.domain.matching.utils import clamp_int
from app.domain.trust_and_safety.config import SCAM_PHRASES, SUSPICIOUS_BIO_PHRASES
from app.domain.trust_and_safety.types import ScamSignalsResult
from app.models.profile import Profile


class ScamSignalDetector:
    """Heuristic scam detector (off-platform, money talk, pressure)."""

    PRESSURE_PATTERNS = (
        r"\b(asap|urgent|right now|today)\b",
        r"\bти повин(ен|на)\b",
        r"\bdon'?t tell anyone\b",
    )

    @classmethod
    def detect_scam_signals(cls, profile: Profile | None, messages: list[str] | None) -> ScamSignalsResult:
        msgs = [m.strip() for m in (messages or []) if (m or "").strip()]
        text = " ".join(msgs).lower()
        signals: list[str] = []
        score = 0

        bio_l = ((getattr(profile, "bio", "") or "").strip().lower() if profile else "")

        if any(p in bio_l for p in SUSPICIOUS_BIO_PHRASES) or any(p in text for p in SUSPICIOUS_BIO_PHRASES):
            score += 35
            signals.append("early_offplatform_push")

        if any(p in bio_l for p in SCAM_PHRASES) or any(p in text for p in SCAM_PHRASES):
            score += 35
            signals.append("money_investment_talk")

        if re.search(r"\b(pay|payment|send)\b.*\b(now|today)\b", text):
            score += 20
            signals.append("payment_pressure")

        for pat in cls.PRESSURE_PATTERNS:
            if re.search(pat, text, flags=re.IGNORECASE):
                score += 15
                signals.append("pressure_tactics")
                break

        scam_risk = clamp_int(score)
        severity = "low"
        if scam_risk >= 80:
            severity = "high"
        elif scam_risk >= 55:
            severity = "medium"

        return ScamSignalsResult(scam_risk=scam_risk, signals=sorted(set(signals)), severity=severity)

