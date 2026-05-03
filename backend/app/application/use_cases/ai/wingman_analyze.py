from __future__ import annotations

from app.infrastructure.ai.provider_factory import get_ai_provider
from app.services.ai.conversation.conversation_analyzer import ConversationAnalyzer


async def analyze_conversation(messages: list[str]) -> dict:
    """Analyze conversation (coach intelligence)."""
    provider = get_ai_provider()
    try:
        return await provider.analyze_conversation(messages)
    except Exception:
        return ConversationAnalyzer.analyze_conversation(messages).to_dict()

