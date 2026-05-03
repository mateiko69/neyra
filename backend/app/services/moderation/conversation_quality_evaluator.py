from __future__ import annotations

from app.domain.matching.utils import clamp_int
from app.domain.trust_and_safety.config import CRINGE_PHRASES, GENERIC_SPAM_OPENERS


class ConversationQualityEvaluator:
    """Anti-cringe, quality-focused conversation evaluator (heuristic)."""

    @staticmethod
    def evaluate_conversation_quality(messages: list[str]) -> dict:
        msgs = [m.strip() for m in (messages or []) if (m or "").strip()]
        if not msgs:
            return {
                "quality_score": 35,
                "dryness_score": 80,
                "engagement_score": 10,
                "cringe_score": 10,
                "flags": ["no_messages"],
                "improvement_advice": ["start with a specific question", "avoid generic greetings"],
            }

        lower = [m.lower() for m in msgs]
        one_word = sum(1 for m in msgs if len(m.split()) <= 2)
        questions = sum(1 for m in msgs if "?" in m)
        repeats = len(lower) - len(set(lower))

        generic = sum(1 for m in lower if any(g == m.strip() for g in GENERIC_SPAM_OPENERS))
        cringe = sum(1 for m in lower if any(p in m for p in CRINGE_PHRASES))

        dryness = clamp_int((one_word / len(msgs)) * 100 + generic * 15)
        engagement = clamp_int((questions / len(msgs)) * 100 + max(0, 30 - dryness * 0.2))
        cringe_score = clamp_int(cringe * 35 + repeats * 10)

        quality = clamp_int(65 + engagement * 0.25 - dryness * 0.35 - cringe_score * 0.25)

        flags: list[str] = []
        advice: list[str] = []
        if one_word >= max(1, len(msgs) // 2):
            flags.append("one_word_replies")
            advice.append("add 1–2 details to keep the flow")
        if generic:
            flags.append("generic_lines")
            advice.append("use something specific from their profile")
        if repeats:
            flags.append("repetitive_messages")
            advice.append("avoid repeating the same phrase")
        if cringe:
            flags.append("cringe_lines")
            advice.append("keep it playful, not over-the-top")
        if dryness >= 70:
            flags.append("dry_conversation")
            advice.append("ask a deeper question or change topic")

        return {
            "quality_score": quality,
            "dryness_score": dryness,
            "engagement_score": engagement,
            "cringe_score": cringe_score,
            "flags": sorted(set(flags)),
            "improvement_advice": advice[:4],
        }

