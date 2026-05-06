from __future__ import annotations

from app.services.ai.ai_request_locale import normalize_ai_request_locale
from app.services.ai.cultural_tone import cultural_tone_prompt_lines
from app.services.localization.locale import language_name


def universal_dating_assistant_system(locale: str) -> str:
    """Locale is a canonical app tag (e.g. en, fr, pt, zh, zh-TW)."""
    loc = normalize_ai_request_locale(locale)
    cultural = cultural_tone_prompt_lines(loc)
    lang_nm = language_name(loc)
    locale_specific = ""
    if loc == "uk":
        locale_specific = "Respond in natural Ukrainian. Do not mix English."
    elif loc == "ru":
        locale_specific = "Respond in natural Russian."
    elif loc == "en":
        locale_specific = "Respond in natural English."
    return f"""You are a dating assistant.

{cultural}

Respond ONLY in the language of this locale: {loc} ({lang_nm})
Reply only in {lang_nm}. Do not use English unless target_language is English. Match the user's latest message language when it is clear.
{locale_specific}

Rules:
- Output MUST be 100% in that language
- DO NOT translate explanations
- DO NOT mix languages
- DO NOT fallback to English (unless locale is en)
- STRICT: Return all suggestions ONLY in {loc}. Do not use English unless locale is 'en'.
- Use natural phrasing; the cultural tone above is a soft hint only

Generate 3 replies (lanes):
- Warm: kind, specific to their last line (not a template interview)
- Flirty: playful romantic tension, still respectful
- Playful: lively / witty curiosity (not heavy "therapy deep")

Each reply:
- 1–2 short sentences, must end with a question
- Must reference a concrete detail from LAST_MESSAGE (word, plan, feeling, or joke)
- no cringe, no pickup lines, no pressure to meet too early
- Never use shallow Ukrainian dodges: «що ти думаєш», «що маєш на увазі» as a generic answer
"""


def assist_openers_json_instructions() -> str:
    return """Return STRICT JSON ONLY (no markdown fences):
{
  "suggestions": [
    {"type": "safe", "text": "..."},
    {"type": "flirty", "text": "..."},
    {"type": "smart", "text": "..."}
  ],
  "recommended_index": 1
}
Types MUST be exactly safe, flirty, smart in that order (Easy → Flirty → Deep lanes).
recommended_index is 0, 1, or 2."""


def wingman_replies_json_instructions() -> str:
    return """Return STRICT JSON ONLY (no markdown fences):
{
  "suggestions": [
    {"text": "...", "style": "safe"},
    {"text": "...", "style": "engaging"},
    {"text": "...", "style": "slightly_bold"}
  ]
}
Map lanes: safe = WARM (kind, specific), engaging = FLIRTY (playful romantic spark), slightly_bold = PLAYFUL (witty / lively, not heavy).
Use each style exactly once. Each text: 1–2 sentences, must end with a question, anchored in LAST_MESSAGE.
Signal fields `partner_message_tone` and `partner_message_intent` in the user block describe how they wrote — match that energy."""


def wingman_openers_json_instructions() -> str:
    return """Return STRICT JSON ONLY (no markdown fences):
{
  "suggestions": [
    {"text": "...", "style": "playful", "reason": "profile-based"},
    {"text": "...", "style": "confident", "reason": "profile-based"},
    {"text": "...", "style": "curious", "reason": "profile-based"}
  ]
}
Each opener <= 220 chars, one sentence, ends with a question; dating-safe, no pickup lines."""


def opener_user_payload_block(
    *,
    match_name: str,
    bio: str,
    interests: list[str],
    city: str,
    tags: list[str],
    conversation_context: list[str],
    style: str,
    plan_tier: str,
) -> str:
    return (
        f"MATCH_NAME: {match_name}\nSTYLE: {style}\nPLAN_TIER: {plan_tier}\n\n"
        f"CITY:\n{city}\n\nBIO:\n{bio}\n\nINTERESTS:\n"
        + "\n".join(interests)
        + "\n\nTAGS:\n"
        + "\n".join(tags)
        + "\n\nCONVERSATION_CONTEXT:\n"
        + "\n".join(conversation_context)
        + "\n"
    )
