"""
Central AI orchestration entrypoints: locale, tier hints, safety, and fallbacks.

Endpoints should call this module instead of ad-hoc provider/ConversationAI paths
so behavior stays consistent across surfaces.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.profile import Profile
from app.services.ai.ai_request_locale import normalize_ai_request_locale, normalize_chat_ai_locale
from app.services.ai.direct_questions import render_direct_answer
from app.services.ai.plan_limits import message_context_limit
from app.services.monetization.subscription_service import SubscriptionService


class AIOrchestrator:
    """Facade over dating AI surfaces (suggestions, openers, brain pack, improve, demo)."""

    @staticmethod
    def resolve_plan_tier(db: Session, user_id: int) -> str:
        try:
            p = SubscriptionService().get_active_plan(db, int(user_id))
        except Exception:
            p = "free"
        return p if p in {"free", "premium", "premium_plus"} else "free"

    @staticmethod
    def ai_context_limit(plan_tier: str | None) -> int:
        return message_context_limit(plan_tier)

    @staticmethod
    def tier_prompt_addon(plan_tier: str | None) -> str:
        from app.services.ai.tier_prompting import capability_prompt_block

        return capability_prompt_block(plan_tier)

    @staticmethod
    def compute_conversation_goal_state(messages: list[dict], *, plan_tier: str, **kwargs):
        """Deterministic meeting-driven goal snapshot for prompts (and Premium+ telemetry)."""
        from app.services.ai.conversation_goal_engine import compute_conversation_goal_state as _goal

        return _goal(messages, plan_tier=plan_tier, **kwargs)

    @staticmethod
    def conversation_goal_prompt_block(state: Any) -> str:
        """System-prompt addendum from ConversationGoalState."""
        from app.services.ai.conversation_goal_engine import goal_state_prompt_block

        return goal_state_prompt_block(state)

    @staticmethod
    def generate_icebreakers(*, my_profile: Profile, other_profile: Profile) -> list[str]:
        if not settings.ENABLE_AI_SUGGESTIONS:
            return ["AI suggestions are currently disabled."]
        from app.services.ai.service import get_ai_provider

        provider = get_ai_provider()
        return provider.first_messages(my_profile, other_profile)

    @staticmethod
    def generate_reply_suggestions(
        *,
        last_message: str,
        me: Profile | None,
        ui_locale: str | None = None,
    ) -> list[str]:
        if not settings.ENABLE_AI_SUGGESTIONS:
            return ["AI suggestions are currently disabled."]
        from app.application.ai.conversation_ai import ConversationAI as _CA

        return _CA.reply_suggestions(last_message, me, ui_locale=ui_locale)

    @staticmethod
    def generate_demo_reply(
        *,
        speaker_profile: Profile | None,
        user_message: str,
        partner_profile: Profile | None = None,
        ui_locale: str | None = None,
    ) -> str | None:
        return render_direct_answer(
            speaker_profile=speaker_profile,
            partner_profile=partner_profile,
            last_user_message=user_message or "",
            ui_locale=ui_locale,
        )

    @staticmethod
    def generate_demo_opener(
        *,
        db: Session,
        demo_user_id: int,
        partner_user_id: int,
        ui_locale: str | None = None,
        style: str = "warm",
        flirt_level: str = "low",
        humor: str = "light",
        relationship_goal: str | None = None,
    ) -> str:
        """
        Demo opener/reply generation via the existing chat-brain pipeline.
        Keeps demo message generation aligned with in-app AI suggestions.
        """
        from app.services.ai.chat_brain_suggestions import ChatBrainRequest, run_chat_brain_suggestions

        locale = normalize_chat_ai_locale(ui_locale or "en")
        style_l = (style or "warm").strip().lower()
        flirt_l = (flirt_level or "low").strip().lower()
        humor_l = (humor or "light").strip().lower()
        goal_l = (relationship_goal or "").strip().lower()

        # Map bot personality into existing conversation modes.
        conversation_mode = "easy"
        if style_l in {"playful", "bold"} or flirt_l in {"medium", "high"}:
            conversation_mode = "playful"
        if style_l == "calm" and flirt_l == "low":
            conversation_mode = "easy"
        if humor_l in {"dry", "soft_tease"} and flirt_l != "high":
            conversation_mode = "confident"
        if goal_l in {"relationship", "serious"} and flirt_l == "low":
            conversation_mode = "deep"

        body = ChatBrainRequest(
            partner_user_id=int(partner_user_id),
            mode="opener",
            language=locale,
            conversation_mode=conversation_mode,
        )
        out = run_chat_brain_suggestions(db, user_id=int(demo_user_id), body=body, plan_tier="premium_plus")
        if not bool(out.get("ok")):
            return ""
        variants = out.get("variants") or {}
        pick_order = ["light", "flirty", "deep"]
        if flirt_l == "high" or style_l in {"playful", "bold"}:
            pick_order = ["flirty", "light", "deep"]
        elif style_l == "calm":
            pick_order = ["deep", "light", "flirty"]
        for key in pick_order:
            text = str(variants.get(key) or "").strip()
            if text:
                return text
        return ""

    @staticmethod
    def generate_chat_brain_pack(
        *,
        db: Session,
        user_id: int,
        body: Any,
        plan_tier: str | None = None,
    ) -> dict[str, Any]:
        from app.services.ai.chat_brain_suggestions import run_chat_brain_suggestions

        tier = plan_tier or AIOrchestrator.resolve_plan_tier(db, user_id)
        return run_chat_brain_suggestions(db, user_id=int(user_id), body=body, plan_tier=tier)

    @staticmethod
    def generate_coach_score(
        *,
        last_messages: list[Any],
        current_user_profile: Profile | None = None,
        partner_profile: Profile | None = None,
        memory: dict[str, Any] | None = None,
        conversation_stage: str | None = None,
        locale: str | None = None,
    ) -> dict[str, Any]:
        from app.services.ai.conversation_coach import assess_conversation

        return assess_conversation(
            last_messages=last_messages,
            current_user_profile=current_user_profile,
            partner_profile=partner_profile,
            memory=memory or {},
            conversation_stage=conversation_stage,
            locale=locale,
        ).to_dict()

    @staticmethod
    async def generate_improve_reply_variants(
        *,
        draft: str,
        conversation_context: list[str],
        user_style: str | None,
        allow_edgy_mode: bool,
        mode: str,
        plan_tier: str,
        locale: str | None,
    ) -> list[dict[str, str]]:
        from app.application.use_cases.ai.wingman_improve_reply import improve_reply_variants

        loc = normalize_chat_ai_locale(locale or "en")
        return await improve_reply_variants(
            draft,
            conversation_context,
            user_style,
            allow_edgy_mode=allow_edgy_mode,
            mode=mode,
            plan_tier=plan_tier,
            locale=loc,
        )

    improve_reply = generate_improve_reply_variants

    @staticmethod
    async def generate_openers(
        *,
        me_profile: Profile | None,
        target_profile: Profile,
        allow_edgy_mode: bool = False,
        locale: str | None = None,
    ) -> list[dict]:
        from app.application.use_cases.ai.wingman_openers import generate_openers as _gen

        return await _gen(me_profile, target_profile, allow_edgy_mode=allow_edgy_mode, locale=locale)

    @staticmethod
    async def run_improve_reply_core(
        *,
        draft: str,
        conversation_context: list[str],
        user_style: str,
        allow_edgy_mode: bool,
        mode: str,
        plan_tier: str,
        locale: str,
        timeout_s: float = 8.0,
    ) -> list[dict[str, str]]:
        """
        Gemini: single provider attempt with timeout, then localized deterministic fallback.
        Other providers: use the shared use-case path (provider + local fallback inside).
        """
        import asyncio

        loc = normalize_chat_ai_locale(locale or "en")
        if str(getattr(settings, "AI_PROVIDER", "") or "").strip().lower() == "gemini":
            from app.services.ai.conversation.reply_assistant import improve_draft_locally
            from app.services.ai.safe_ai import safe_ai_generate_async
            from app.services.ai.service import get_ai_provider

            provider = get_ai_provider()

            async def _improve_gemini() -> list[dict[str, str]]:
                out = await asyncio.wait_for(
                    provider.improve_reply_draft(
                        draft,
                        conversation_context or [],
                        user_style,
                        mode=mode,
                        plan_tier=plan_tier,
                        locale=loc,
                    ),
                    timeout=timeout_s,
                )
                suggestions = out.get("suggestions") if isinstance(out, dict) else None
                if not suggestions or len(suggestions) < 3:
                    raise ValueError("insufficient_improve_suggestions")
                return [{"text": s.get("text", ""), "style": s.get("style", "safe")} for s in suggestions[:3]]

            def _improve_fb() -> list[dict[str, str]]:
                rows = improve_draft_locally(
                    draft,
                    conversation_context,
                    user_style,
                    allow_edgy_mode=allow_edgy_mode,
                    locale=loc,
                )
                return [{"text": x["text"], "style": x["style"]} for x in rows[:3]]

            return await safe_ai_generate_async(_improve_gemini, _improve_fb, endpoint="improve-reply/core", locale=loc)

        return await AIOrchestrator.generate_improve_reply_variants(
            draft=draft,
            conversation_context=conversation_context,
            user_style=user_style,
            allow_edgy_mode=allow_edgy_mode,
            mode=mode,
            plan_tier=plan_tier,
            locale=loc,
        )

    @staticmethod
    async def complete_typed_opener_request(
        *,
        req: Any,
        partner_nm: str | None,
        opener_city: str,
        opener_tags: list[str],
        plan_tier: str,
        trust_bucket: str,
        normalized: str,
    ) -> dict[str, Any]:
        """Provider + finalize path for POST /ai/opener (lazy-imports endpoint helpers to avoid cycles)."""
        import asyncio
        import logging

        from app.api.v1.endpoints.ai import (
            _AI_PROVIDER_TIMEOUT_S,
            _coerce_provider_opener_rows,
            _finalize_typed_opener_items,
            _map_opener_recommended_index,
            _OPENER_TYPES_ORDER,
            _safe_opener_suggestions,
            _with_timeout,
        )
        from app.services.ai.ai_request_locale import normalize_ai_request_locale
        from app.services.ai.locale_rewrite import batch_translate_lines
        from app.services.ai.output_script_locale import text_matches_requested_locale
        from app.services.ai.service import get_ai_provider

        provider_used = "fallback"
        fallback_reason: str | None = None
        typed_from_provider: list[dict[str, str]] | None = None
        rec_raw = 1
        provider = get_ai_provider()
        try:
            from app.api.v1.endpoints.ai import _clean_name

            out = await _with_timeout(
                provider.opener_suggestions(
                    match_name=_clean_name(req.match_name),
                    bio=(req.bio or ""),
                    interests=req.interests or [],
                    city=opener_city,
                    tags=opener_tags,
                    conversation_context=req.conversation_context or [],
                    style=req.style or "playful",
                    plan_tier=plan_tier,
                    locale=req.locale,
                ),
                timeout_s=_AI_PROVIDER_TIMEOUT_S,
            )
            if isinstance(out, dict):
                try:
                    rec_raw = int(out.get("recommended_index") if out.get("recommended_index") is not None else 1)
                except (TypeError, ValueError):
                    rec_raw = 1
            rec_raw = max(0, min(2, rec_raw))
            rows = out.get("suggestions") if isinstance(out, dict) else None
            typed_from_provider = _coerce_provider_opener_rows(rows if isinstance(rows, list) else None)
            if not any(x.get("text") for x in typed_from_provider):
                fallback_reason = "insufficient_safe"
                typed_from_provider = None
            else:
                cname = provider.__class__.__name__.lower()
                provider_used = "gemini" if cname.startswith("gemini") else "provider"
        except asyncio.TimeoutError:
            fallback_reason = "timeout"
        except Exception:
            fallback_reason = "exception"

        if not typed_from_provider:
            provider_used = "fallback"
            strs = _safe_opener_suggestions(req)
            typed_from_provider = [{"type": ot, "text": strs[i] if i < len(strs) else ""} for i, ot in enumerate(_OPENER_TYPES_ORDER)]

        pre_safe_texts = [x.get("text") or "" for x in typed_from_provider][:3]
        final_items = _finalize_typed_opener_items(typed_from_provider, partner_name=partner_nm, locale=req.locale)
        suggestions = [x["text"] for x in final_items]
        recommended_index = _map_opener_recommended_index(pre_safe_texts, suggestions, rec_raw)

        loc_ai = normalize_ai_request_locale(req.locale)
        if loc_ai != "en" and final_items:
            texts_try = [x["text"] for x in final_items]
            if any(not text_matches_requested_locale(t, loc_ai) for t in texts_try):
                try:
                    tr = await batch_translate_lines(texts_try, loc_ai)
                    if len(tr) == len(final_items):
                        for i, row in enumerate(final_items):
                            row["text"] = tr[i]
                        suggestions = [x["text"] for x in final_items]
                except Exception:
                    pass

        log = logging.getLogger("neyra.ai")
        if len(final_items) < 3:
            log.warning("ai_opener_fallback_used", extra={"locale": (req.locale or "")})
            recommended_index = 1

        log.info(
            "ai_assist_opener served",
            extra={
                "provider_used": provider_used,
                "fallback_reason": fallback_reason,
                "trust_bucket": trust_bucket,
                "requested_mode": normalized,
                "effective_mode": req.style or "",
                "plan_tier": plan_tier,
                "ctx_len": len(req.conversation_context or []),
            },
        )
        return {
            "items": final_items,
            "suggestions": suggestions[:3],
            "recommended_index": max(0, min(2, recommended_index)),
        }
