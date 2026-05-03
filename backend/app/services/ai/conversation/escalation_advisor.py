from __future__ import annotations

from app.domain.ai.conversation_analysis import ConversationAnalysis


class EscalationAdvisor:
    """Suggests next conversational move based on analysis (coach behavior)."""

    @staticmethod
    def suggest_next_step(analysis: ConversationAnalysis) -> dict:
        suggestions: list[str] = []
        if "no_messages" in analysis.flags:
            suggestions = ["start with a curious question", "use a playful opener"]
        elif analysis.energy_level == "low":
            suggestions = ["ask a deeper question", "change topic", "add a bit of humor"]
        elif analysis.energy_level == "medium":
            suggestions = ["mirror their vibe", "introduce a personal story", "ask a fun either-or question"]
        else:  # high
            if analysis.risk_of_drop < 35:
                suggestions = ["propose meeting", "suggest a quick call", "pick a specific plan"]
            else:
                suggestions = ["lock in the topic with a concrete question", "add playful challenge"]

        return {
            "suggestions": suggestions[:4],
            "rationale": "Based on interest/energy signals",
        }

