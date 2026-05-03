from __future__ import annotations

import re

from app.services.moderation.message_risk_evaluator import MessageRiskEvaluator


def sanitize_user_text(text: str, max_len: int = 800) -> str:
    t = (text or "").strip()
    t = re.sub(r"[\x00-\x08\x0B\x0C\x0E-\x1F]", "", t)
    if len(t) > max_len:
        t = t[:max_len] + "…"
    return t


def safe_output_or_none(text: str) -> str | None:
    res = MessageRiskEvaluator.evaluate_message_risk(text, conversation_context=[], allow_edgy_mode=False)
    if not res.allowed:
        return None
    return text

