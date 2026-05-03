from __future__ import annotations

from app.domain.ai.conversation_analysis import ConversationAnalysis
from app.domain.matching.utils import clamp_int
from app.services.ai.conversation.escalation_advisor import EscalationAdvisor
from app.infrastructure.ai.provider_factory import get_ai_provider
from app.services.ai.safe_ai import safe_ai_generate_async


async def suggest_next_step(analysis_payload: dict) -> dict:
    """Suggest next step based on analysis payload from the analyzer endpoint."""

    analysis = ConversationAnalysis(
        interest_level=clamp_int(float(analysis_payload.get("interest_level", 0))),
        response_quality=clamp_int(float(analysis_payload.get("response_quality", 0))),
        risk_of_drop=clamp_int(float(analysis_payload.get("risk_of_drop", 0))),
        energy_level=analysis_payload.get("energy_level", "low"),
        flags=list(analysis_payload.get("flags", [])) if isinstance(analysis_payload.get("flags", []), list) else [],
    )
    provider = get_ai_provider()

    async def _next_step_gemini() -> dict:
        return await provider.suggest_next_step(analysis.to_dict())

    def _next_step_fb() -> dict:
        return EscalationAdvisor.suggest_next_step(analysis)

    return await safe_ai_generate_async(_next_step_gemini, _next_step_fb, endpoint="next-step", locale=None)

