from __future__ import annotations

from app.services.moderation.message_risk_evaluator import MessageRiskEvaluator


def evaluate_message_risk(message: str, conversation_context: list[str] | None = None, *, allow_edgy_mode: bool = False) -> dict:
    return MessageRiskEvaluator.evaluate_message_risk(message, conversation_context, allow_edgy_mode=allow_edgy_mode).to_dict()

