from __future__ import annotations

from app.domain.ai.conversation_analysis import ConversationAnalysis
from app.domain.matching.utils import clamp_int


class ConversationAnalyzer:
    """Heuristic conversation analyzer (deterministic, testable)."""

    @staticmethod
    def analyze_conversation(messages: list[str]) -> ConversationAnalysis:
        msgs = [m.strip() for m in (messages or []) if (m or "").strip()]
        if not msgs:
            return ConversationAnalysis(
                interest_level=40,
                response_quality=40,
                risk_of_drop=70,
                energy_level="low",
                flags=["no_messages"],
            )

        lengths = [len(m) for m in msgs]
        avg_len = sum(lengths) / max(1, len(lengths))
        questions = sum(1 for m in msgs if "?" in m)
        emojis = sum(1 for m in msgs if any(e in m for e in ("🙂", "😉", "😂", "❤️", "✨")))

        short_replies = sum(1 for m in msgs if len(m) <= 8)
        flags: list[str] = []
        if short_replies >= max(1, len(msgs) // 2):
            flags.append("short_replies")

        dry_tone = 1 if avg_len < 18 and questions == 0 else 0
        if dry_tone:
            flags.append("dry_tone")

        response_quality = clamp_int((avg_len / 60) * 100 + questions * 6 + emojis * 3)
        interest_level = clamp_int(45 + questions * 8 + emojis * 4 + (avg_len / 40) * 20 - short_replies * 8)
        risk_of_drop = clamp_int(75 - interest_level * 0.5 - response_quality * 0.3 + short_replies * 10 + dry_tone * 12)

        energy_level = "low"
        if interest_level >= 70 and response_quality >= 60:
            energy_level = "high"
        elif interest_level >= 55:
            energy_level = "medium"

        return ConversationAnalysis(
            interest_level=interest_level,
            response_quality=response_quality,
            risk_of_drop=risk_of_drop,
            energy_level=energy_level,
            flags=flags,
        )

