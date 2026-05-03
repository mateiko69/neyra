from __future__ import annotations

import httpx

from app.core.config import settings
from app.services.ai.ai_request_locale import normalize_ai_request_locale
from app.services.ai.cache import cache_get, cache_key, cache_set
from app.services.ai.conversation.last_message_signals import format_wingman_replies_user_prompt
from app.services.ai.dating_assistant_prompts import (
    assist_openers_json_instructions,
    opener_user_payload_block,
    universal_dating_assistant_system,
    wingman_openers_json_instructions,
    wingman_replies_json_instructions,
)
from app.services.ai.locale import ensure_locale, normalize_locale
from app.services.ai.prompt_loader import load_prompt
from app.services.ai.providers.base import AIProvider
from app.services.ai.safety import sanitize_user_text, safe_output_or_none
from app.services.ai.suggestion_enforcement import (
    post_process_assist_openers,
    post_process_wingman_openers,
    post_process_wingman_replies,
)
from app.services.ai.plan_limits import message_context_limit
from app.services.ai.structured import AssistOpenersOut, ConversationAnalysisOut, DatingCoachOut, NextStepOut, OpenersOut, RepliesOut
from app.services.ai.gemini_client import GeminiClient, GeminiError


class GeminiProvider(AIProvider):
    """Gemini provider using Generative Language REST API with strict JSON outputs."""

    def __init__(self, http_client: httpx.AsyncClient | None = None):
        self._client = http_client or httpx.AsyncClient()
        self._gemini = GeminiClient(self._client)

    def first_messages(self, me, other):
        return []

    def reply_suggestions(self, last_message):
        return []

    def analyze_profile(self, profile):
        return {"provider": "gemini", "note": "Use wingman endpoints."}

    async def generate_openers(self, me, other, *, locale: str | None = None) -> dict:
        loc_key = normalize_ai_request_locale(locale)
        payload = {"me": _profile_summary(me), "target": _profile_summary(other), "locale": loc_key}
        key = cache_key("openers", payload)
        cached = cache_get(key)
        if cached:
            return cached
        system = universal_dating_assistant_system(loc_key) + "\n\n" + wingman_openers_json_instructions()
        user = f"ME_PROFILE:\n{payload['me']}\n\nTARGET_PROFILE:\n{payload['target']}\n"
        out = await self._generate_json(system, user, OpenersOut, model=settings.GEMINI_CHAT_MODEL)
        safe = await post_process_wingman_openers(out.model_dump(), loc_key)
        cache_set(key, safe, settings.AI_CACHE_TTL_SECONDS)
        return safe

    async def generate_replies(self, last_message: str, context: list[str], style: str, *, locale: str | None = None) -> dict:
        loc_key = normalize_ai_request_locale(locale)
        payload = {
            "last_message": sanitize_user_text(last_message, 400),
            "context": [sanitize_user_text(x, 240) for x in (context or [])][-10:],
            "style": style,
            "locale": loc_key,
        }
        key = cache_key("replies", payload)
        cached = cache_get(key)
        if cached:
            return cached
        user = format_wingman_replies_user_prompt(
            last_message=str(payload.get("last_message") or ""),
            context_lines=payload["context"],
            user_style=style,
        )
        system = (
            universal_dating_assistant_system(loc_key)
            + "\n\n"
            + wingman_replies_json_instructions()
            + "\n\n"
            + "Hard quality rules: short, specific, contextual, question-ending replies only."
        )
        out = await self._generate_json(system, user, RepliesOut, model=settings.GEMINI_CHAT_MODEL)
        safe = await post_process_wingman_replies(out.model_dump(), loc_key)
        cache_set(key, safe, settings.AI_CACHE_TTL_SECONDS)
        return safe

    async def analyze_conversation(self, messages: list[str]) -> dict:
        ctx = "\n".join([sanitize_user_text(m, 240) for m in (messages or [])][-10:])
        out = await self._generate_json(
            load_prompt("conversation_analysis_prompt.txt"),
            f"MESSAGES:\n{ctx}\n",
            ConversationAnalysisOut,
            model=settings.GEMINI_ANALYSIS_MODEL,
        )
        return out.model_dump()

    async def improve_reply_draft(
        self,
        draft: str,
        context: list[str],
        user_style: str,
        *,
        mode: str | None = None,
        plan_tier: str | None = None,
        locale: str | None = None,
    ) -> dict:
        loc_key = normalize_ai_request_locale(locale)
        _lim = message_context_limit(plan_tier)
        payload = {
            "draft": sanitize_user_text(draft, 600),
            "context": [sanitize_user_text(x, 240) for x in (context or [])][-_lim:],
            "user_style": sanitize_user_text(user_style, 80),
            "mode": sanitize_user_text(mode or "polish", 32),
            "plan_tier": sanitize_user_text(plan_tier or "free", 32),
            "locale": loc_key,
        }
        key = cache_key("improve_reply", payload)
        cached = cache_get(key)
        if cached:
            return cached
        improve_rules = load_prompt("improve_reply_prompt.txt").replace(
            "Match the language of the DRAFT and CONTEXT (Ukrainian if they use Ukrainian).",
            "Follow the system locale for all variants (ignore draft language if it conflicts).",
        )
        system = universal_dating_assistant_system(loc_key) + "\n\n" + wingman_replies_json_instructions() + "\n\n" + improve_rules
        user = (
            f"DRAFT:\n{payload['draft']}\n\nCONTEXT:\n"
            + "\n".join(payload["context"])
            + f"\n\nUSER_STYLE: {payload['user_style']}\nMODE: {payload['mode']}\nPLAN_TIER: {payload['plan_tier']}\n"
        )
        out = await self._generate_json(system, user, RepliesOut, model=settings.GEMINI_CHAT_MODEL)
        safe = await post_process_wingman_replies(out.model_dump(), loc_key)
        cache_set(key, safe, settings.AI_CACHE_TTL_SECONDS)
        return safe

    async def opener_suggestions(
        self,
        *,
        match_name: str,
        bio: str,
        interests: list[str],
        conversation_context: list[str],
        style: str,
        plan_tier: str,
        locale: str | None = None,
        city: str = "",
        tags: list[str] | None = None,
    ) -> dict:
        loc_key = normalize_ai_request_locale(locale)
        payload = {
            "match_name": sanitize_user_text(match_name, 80),
            "bio": sanitize_user_text(bio, 800),
            "interests": [sanitize_user_text(x, 40) for x in (interests or [])][:8],
            "city": sanitize_user_text(city, 120),
            "tags": [sanitize_user_text(x, 40) for x in (tags or [])][:8],
            "conversation_context": [sanitize_user_text(x, 240) for x in (conversation_context or [])][-10:],
            "style": sanitize_user_text(style, 32),
            "plan_tier": sanitize_user_text(plan_tier, 32),
            "locale": loc_key,
        }
        key = cache_key("opener_suggestions_v2", payload)
        cached = cache_get(key)
        if cached:
            return cached
        system = universal_dating_assistant_system(loc_key) + "\n\n" + assist_openers_json_instructions()
        user = opener_user_payload_block(
            match_name=payload["match_name"],
            bio=payload["bio"],
            interests=payload["interests"],
            city=payload["city"],
            tags=payload["tags"],
            conversation_context=payload["conversation_context"],
            style=payload["style"],
            plan_tier=payload["plan_tier"],
        )
        out = await self._generate_json(system, user, AssistOpenersOut, model=settings.GEMINI_CHAT_MODEL)
        safe = await post_process_assist_openers(out.model_dump(), loc_key)
        cache_set(key, safe, settings.AI_CACHE_TTL_SECONDS)
        return safe

    async def dating_coach_guidance(self, messages: list[str], *, locale: str | None = None) -> dict:
        ctx = "\n".join([sanitize_user_text(m, 240) for m in (messages or [])][-12:])
        out = await self._generate_json(
            _inject_locale_guard(load_prompt("dating_coach_prompt.txt"), locale),
            f"MESSAGES:\n{ctx}\n",
            DatingCoachOut,
            model=settings.GEMINI_CHAT_MODEL,
        )
        return _post_filter_coach_gemini(out.model_dump(), locale)

    async def suggest_next_step(self, analysis: dict) -> dict:
        out = await self._generate_json(
            load_prompt("next_step_prompt.txt"),
            f"ANALYSIS_JSON:\n{analysis}\n",
            NextStepOut,
            model=settings.GEMINI_ANALYSIS_MODEL,
        )
        return out.model_dump()

    async def _generate_json(
        self,
        system_prompt: str,
        user_prompt: str,
        out_model,
        *,
        model: str | None = None,
        surface: str | None = "gemini-provider",
    ):
        try:
            return await self._gemini.generate_json(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                out_model=out_model,
                timeout_s=10.0,
                model=model,
                surface=surface,
            )
        except GeminiError:
            raise


def _profile_summary(p) -> str:
    if not p:
        return "N/A"
    bio = sanitize_user_text(getattr(p, "bio", "") or "", 380)
    interests = sanitize_user_text(getattr(p, "interests", "") or "", 200)
    tags = sanitize_user_text(getattr(p, "lifestyle_tags", "") or "", 200)
    goal = sanitize_user_text(getattr(p, "relationship_goal", "") or "", 60)
    city = sanitize_user_text(getattr(p, "city", "") or "", 60)
    name = sanitize_user_text(getattr(p, "display_name", "") or "", 60)
    return f"name={name}\ncity={city}\ngoal={goal}\ninterests={interests}\ntags={tags}\nbio={bio}"


def _inject_locale_guard(system_prompt: str, locale: str | None) -> str:
    from app.services.ai.cultural_tone import cultural_tone_prompt_lines

    loc = normalize_ai_request_locale(locale)
    guard = (
        f"{cultural_tone_prompt_lines(loc)}\n"
        f"Respond ONLY in the language of locale {loc}. "
        "Do not mix languages. If you mention a city, keep the entire phrase in that language."
    )
    return f"{guard}\n\n{system_prompt}"


def _post_filter_coach_gemini(data: dict, locale: str | None) -> dict:
    def line(key: str, fallback: str) -> str:
        t = safe_output_or_none(str(data.get(key, "") or "")) or fallback
        return t.strip()[:320]

    loc = normalize_locale(locale)
    if loc == "en":
        tone_fb = "Warm, calm tone; short messages and one clear question."
        ask_fb = "Ask about one specific detail from their last message."
        avoid_fb = "Pressure, long monologues, and dry replies without a next step."
    elif loc == "ru":
        tone_fb = "Тёплый, спокойный тон; короткие реплики и один понятный вопрос."
        ask_fb = "Спроси про одну конкретную деталь из их последнего сообщения."
        avoid_fb = "Давление, длинные монологи и сухие ответы без продолжения."
    else:
        tone_fb = "Теплий, спокійний тон; короткі репліки й одне чітке питання."
        ask_fb = "Запитай про одну конкретну деталь з їхнього останнього повідомлення."
        avoid_fb = "Тиск, довгі монологи й сухі відповіді без продовження розмови."
    return {
        "tone": ensure_locale(line("tone", tone_fb), loc, {"en": tone_fb, "ru": tone_fb if loc == "ru" else "Тёплый, спокойный тон; короткие реплики и один понятный вопрос.", "uk": tone_fb if loc == "uk" else "Теплий, спокійний тон; короткі репліки й одне чітке питання."}),
        "ask_next": ensure_locale(line("ask_next", ask_fb), loc, {"en": ask_fb, "ru": ask_fb if loc == "ru" else "Спроси про одну конкретную деталь из их последнего сообщения.", "uk": ask_fb if loc == "uk" else "Запитай про одну конкретну деталь з їхнього останнього повідомлення."}),
        "avoid": ensure_locale(line("avoid", avoid_fb), loc, {"en": avoid_fb, "ru": avoid_fb if loc == "ru" else "Давление, длинные монологи и сухие ответы без продолжения.", "uk": avoid_fb if loc == "uk" else "Тиск, довгі монологи й сухі відповіді без продовження розмови."}),
    }
