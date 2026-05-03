from __future__ import annotations

from app.core.config import settings
from app.models.profile import Profile
from app.services.ai.ai_request_locale import normalize_ai_request_locale
from app.services.ai.centralized import fallback_reply_triplet
from app.services.ai.direct_questions import detect_direct_intent, resolve_output_locale
from app.services.ai.direct_questions import render_direct_answer
from app.services.ai.service import get_ai_provider
from app.services.ai.suggestion_locale import ensure_suggestions_locale


class ConversationAI:
    """Conversation assistance (icebreakers, reply suggestions)."""

    @staticmethod
    def icebreakers(me: Profile, other: Profile) -> list[str]:
        if not settings.ENABLE_AI_SUGGESTIONS:
            return ["AI suggestions are currently disabled."]
        provider = get_ai_provider()
        return provider.first_messages(me, other)

    @staticmethod
    def reply_suggestions(last_message: str, me: Profile | None = None, *, ui_locale: str | None = None) -> list[str]:
        if not settings.ENABLE_AI_SUGGESTIONS:
            return ["AI suggestions are currently disabled."]
        msg = last_message or ""
        loc_hint = normalize_ai_request_locale(ui_locale or (getattr(me, "preferred_language", None) if me else "en"))

        intent = detect_direct_intent(msg)
        if intent and me:
            direct = render_direct_answer(
                speaker_profile=me,
                partner_profile=None,
                last_user_message=msg,
                ui_locale=loc_hint,
            )
            if direct:
                out_loc = resolve_output_locale(msg, loc_hint)
                fb = fallback_reply_triplet(locale=out_loc)
                return [direct, fb[0], fb[1]]

        provider = get_ai_provider()
        raw = provider.reply_suggestions(msg)
        return ensure_suggestions_locale(list(raw or []), locale=loc_hint)
