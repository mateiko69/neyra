from __future__ import annotations

from app.services.moderation.conversation_quality_evaluator import ConversationQualityEvaluator


def evaluate_conversation_quality(messages: list[str]) -> dict:
    return ConversationQualityEvaluator.evaluate_conversation_quality(messages)

