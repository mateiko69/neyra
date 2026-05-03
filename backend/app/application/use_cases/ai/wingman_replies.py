from __future__ import annotations

import logging
import re

from app.infrastructure.ai.provider_factory import get_ai_provider
from app.services.ai.ai_request_locale import normalize_ai_request_locale
from app.services.ai.conversation.reply_generator import ReplyGenerator

logger = logging.getLogger("neyra.ai.replies")


def _ensure_question(text: str) -> str:
    s = " ".join((text or "").strip().split())
    if not s:
        return "What part of that matters most to you?"
    if "?" not in s:
        s = s.rstrip(".!… ") + "?"
    return s[:240]


def _is_generic_weak(text: str) -> bool:
    low = " ".join((text or "").strip().lower().split())
    if not low:
        return True
    weak = {
        "ok",
        "okay",
        "nice",
        "cool",
        "sure",
        "sounds good",
        "k",
        "мм",
        "ага",
        "ясно",
        "ок",
        "норм",
    }
    if low in weak:
        return True
    return len(low) < 6


def _strong_fallback_triplet(last_message: str, *, locale: str | None) -> list[dict]:
    loc = normalize_ai_request_locale(locale)
    msg = " ".join((last_message or "").strip().split())
    topic = "that" if not msg else msg[:80]
    if loc == "uk":
        from app.services.ai.conversation.contextual_fallback_triples import uk_reply_fallback_three_lines

        safe, slightly_bold, engaging = uk_reply_fallback_three_lines(last_message or "", continue_mode=True)
        return [
            {"style": "safe", "text": _ensure_question(safe)},
            {"style": "slightly_bold", "text": _ensure_question(slightly_bold)},
            {"style": "engaging", "text": _ensure_question(engaging)},
        ]
    if loc == "ru":
        safe = _ensure_question("Ты интересно это подаешь 🙂 а что в этой истории зацепило тебя сильнее всего?")
        slightly_bold = _ensure_question("С тобой эта тема звучит еще лучше 😉 что бы ты рассказал(а) об этом за кофе?")
        engaging = _ensure_question(f"Когда ты говоришь про «{topic}», это больше про эмоцию или про опыт?")
    else:
        safe = _ensure_question("You make that sound interesting 🙂 what part of it hit you most?")
        slightly_bold = _ensure_question("This topic sounds better with you already 😉 what would you tell me first over coffee?")
        engaging = _ensure_question(f"When you talk about '{topic}', is it more about the feeling or the experience for you?")
    return [
        {"style": "safe", "text": safe},
        {"style": "slightly_bold", "text": slightly_bold},
        {"style": "engaging", "text": engaging},
    ]


def _valid_suggestions(rows: list[dict] | None) -> bool:
    vals = rows or []
    if len(vals) < 3:
        return False
    for r in vals[:3]:
        t = str((r or {}).get("text") or "").strip()
        if not t or _is_generic_weak(t) or "?" not in t:
            return False
    return True


async def generate_replies(
    last_message: str,
    conversation_context: list[str] | None,
    user_style: str,
    *,
    allow_edgy_mode: bool = False,
    locale: str | None = None,
) -> list[dict]:
    """Generate reply options via provider, with deterministic fallback."""

    provider = get_ai_provider()
    try:
        out = await provider.generate_replies(last_message, conversation_context or [], user_style, locale=locale)
        suggestions = out.get("suggestions") if isinstance(out, dict) else None
        if _valid_suggestions(suggestions):
            return list(suggestions)[:3]
        logger.info("ai_fallback_used", extra={"endpoint": "generate_replies", "reason": "parse_error"})
    except Exception as e:
        reason = "upstream_unavailable"
        code = str(getattr(e, "code", "") or "").strip().lower()
        if "parse_error" in code:
            reason = "parse_error"
        elif "timeout" in code:
            reason = "timeout"
        elif "unavailable" in code or "503" in code:
            reason = "gemini_503"
        logger.info("ai_fallback_used", extra={"endpoint": "generate_replies", "reason": reason})
    base = ReplyGenerator.generate_replies(
        last_message,
        conversation_context=conversation_context,
        user_style=user_style,
        allow_edgy_mode=allow_edgy_mode,
        locale=locale,
    )
    if _valid_suggestions(base):
        return list(base)[:3]
    return _strong_fallback_triplet(last_message, locale=locale)

