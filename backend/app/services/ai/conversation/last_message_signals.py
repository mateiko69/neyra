"""
Lightweight heuristics for partner last-message tone + intent (dating chat).

Used to steer reply generation toward contextual, non-generic suggestions.
"""

from __future__ import annotations


def _compact_low(s: str) -> str:
    return " ".join((s or "").strip().lower().split())


def detect_partner_tone(last_message: str) -> str:
    """Rough tone bucket for the partner's last line."""
    t = last_message or ""
    low = _compact_low(t)
    if not low:
        return "neutral"
    if any(x in low for x in ("сором", "не впевн", "не знаю чи", "можливо", "напевно")):
        return "tentative"
    if sum(1 for c in t if ord(c) > 127 and c in "😀😃😄😁😉😊🙂😍😂🥹❤️✨") >= 1 or any(
        x in low for x in ("ахах", "лол", "хах", "haha", "lol", "hehe")
    ):
        return "playful"
    if t.count("!") >= 2 or any(x in low for x in ("кайф", "супер", "круто", "вау", "amazing", "love it")):
        return "upbeat"
    if any(
        x in low
        for x in (
            "втом",
            "сумн",
            "тривож",
            "важко",
            "відчува",
            "пережива",
            "соромно",
            "sad",
            "tired",
            "anxious",
        )
    ):
        return "reflective"
    return "neutral"


def detect_partner_intent(last_message: str) -> str:
    """
    Coarse intent for routing replies: question-led chat, playful banter, or deeper emotional thread.

    Maps to product lanes: reference explicitly in prompts (warm / flirty / playful reply styles).
    """
    t = (last_message or "").strip()
    low = _compact_low(t)
    if not low:
        return "playful"
    if "?" in t or any(
        low.startswith(p)
        for p in (
            "чому",
            "навіщо",
            "коли",
            "де ",
            "куди",
            "хто",
            "що ",
            "як ",
            "чи ",
            "скільки",
            "which ",
            "what ",
            "how ",
            "why ",
            "when ",
            "where ",
        )
    ):
        return "question"
    if any(
        x in low
        for x in (
            "відчува",
            "люблю",
            "боюся",
            "мрію",
            "важливо",
            "емоц",
            "сум",
            "feel",
            "afraid",
            "scared",
            "hope",
        )
    ):
        return "deep"
    if any(x in low for x in ("ахах", "лол", "жарт", "прикол", "мем", "haha", "lol", "jk")):
        return "playful"
    return "playful"


def build_last_message_reply_context(last_message: str) -> dict[str, str]:
    """Structured hints for prompts (JSON-serializable strings)."""
    tone = detect_partner_tone(last_message)
    intent = detect_partner_intent(last_message)
    excerpt = (last_message or "").strip().replace("\n", " ")[:420]

    if intent == "question":
        guidance = (
            "They asked something or led with a question: react to their exact point first "
            "(do not answer with generic meta-questions). Then ask ONE new, specific follow-up tied to their words."
        )
    elif intent == "deep":
        guidance = (
            "Tone feels personal/emotional: stay warm and specific; mirror their topic without cold interview prompts."
        )
    else:
        guidance = (
            "Tone is playful/light: match energy with specifics from their message — witty or curious, not templated."
        )

    return {
        "tone": tone,
        "intent": intent,
        "guidance_for_replies": guidance,
        "last_message_excerpt": excerpt,
    }


def format_wingman_replies_user_prompt(*, last_message: str, context_lines: list[str], user_style: str) -> str:
    """Shared user block for `generate_replies` (all providers)."""
    sig = build_last_message_reply_context(last_message)
    ctx = "\n".join(context_lines)
    return (
        f"LAST_MESSAGE:\n{last_message}\n\nCONTEXT:\n{ctx}\n"
        f"\nUSER_STYLE: {user_style}\n"
        f"PARTNER_MESSAGE_TONE: {sig.get('tone') or ''}\n"
        f"PARTNER_MESSAGE_INTENT: {sig.get('intent') or ''}\n"
        f"REPLY_GUIDANCE: {sig.get('guidance_for_replies') or ''}\n"
        "\nREPLY_REQUIREMENTS:\n"
        "- Each suggestion must anchor in LAST_MESSAGE (cite a concrete detail: topic, plan, feeling).\n"
        "- 1–2 sentences maximum.\n"
        "- Must end with a clear question.\n"
        "- Avoid generic fillers like 'ok', 'nice', 'cool'.\n"
        "- Do not use Ukrainian clichés: «що ти думаєш», «що маєш на увазі».\n"
    )
