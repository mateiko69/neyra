from datetime import datetime, UTC, timedelta, timezone
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_
import asyncio
import os
import json
import random
import re
import logging
from typing import Any
from fastapi import APIRouter, Depends, HTTPException, Body, Request
from app.api.api_errors import api_error
from app.api.deps import get_db, get_current_user
from app.core.config import settings
from app.models.user import User
from app.models.profile import Profile
from app.models.message import Message
from app.models.user_ai_memory import UserAiMemory
from app.application.ai.profile_ai import ProfileAI
from app.application.use_cases.ai.wingman_replies import generate_replies
from app.application.use_cases.ai.wingman_analyze import analyze_conversation
from app.application.use_cases.ai.wingman_next_step import suggest_next_step
from app.services.ai.chat_brain_suggestions import ChatBrainRequest, fallback_pack as chat_brain_fallback_pack
from app.services.ai.ai_locale_logging import log_ai_locale_context, log_ai_locale_result
from app.services.ai.ai_request_locale import normalize_ai_request_locale
from app.services.ai.locale import normalize_chat_ai_locale
from app.services.ai.locale_decision import resolve_ai_locale_decision
from app.services.ai.locale_prompt_language_names import english_language_name_for_ai_prompt
from app.services.ai.coach_advice_locales import coach_advice_for_move
from app.services.ai.ai_fallback_phrases import opener_typed_fallback, start_strategy_wait_reason, timed_revive_triple
from app.services.ai.rate_limit import RateLimitExceeded, enforce_ai_limits
from app.services.ai.usage_limits import AiLimitReached, AiNotUnlocked, AiRapidCooldown, enforce_and_consume_ai_usage
from app.services.ai.plan_limits import message_context_limit
from app.services.ai.conversation.reply_assistant import improve_draft_locally
from app.services.premium import has_premium_access
from app.services.ai.safety.chat_safety import filter_chat_suggestions
from app.services.analytics import track_event
from app.services.ai_product_analytics import mark_ai_suggestion_wave
from app.services.retention.daily_boosts import (
    FREE_TIER_AI_REPLY_SLOTS_PER_DAY,
    consume_daily_boost_slot,
    get_daily_boosts_state,
)
from app.services.app_language import locale_from_accept_language_header
from app.services.ai.locale_pipeline import (
    log_ai_locale_resolved,
    log_ai_response_debug,
    resolve_ai_locale_strict_chain,
)
from app.services.monetization.subscription_service import SubscriptionService
from app.infrastructure.ai.provider_factory import get_ai_provider
from app.services.ai.gemini_client import GeminiClient, GeminiError, log_ai_provider_final
from app.services.ai.safe_ai import log_ai_fallback_triggered, safe_ai_generate_async
from app.services.ai.diagnostics import incr_fallback_24h, set_last_gemini_error, set_last_provider_used
from app.services.ai.cache import get_redis
from app.services.ai.conversation.readiness_score import score_readiness
from app.services.ai.conversation.coach_rules import coach_intervention
from app.services.ai.conversation.escalation_readiness import escalation_readiness
from app.services.ai.conversation.recovery_rules import recovery_intervention
from app.services.ai.compatibility.service import CompatibilityService
from app.services.trust.profile_quality import compute_profile_quality
from app.services.trust.verification_state import is_verified_profile
from app.services.safety import is_blocked
from app.services.match_partner import users_are_matched
from app.services.ai.conversation.reply_generator import ReplyGenerator
from app.services.ai.safety import sanitize_user_text
from app.services.ai.structured import ChatCopilotOut, CopilotTripleLineOut
from app.services.premium_trial import maybe_start_premium_trial
from app.models.user_ai_profile import UserAiProfile
from app.utils.media_urls import normalize_photo_url
from app.services.ai.conversation.closer_meeting import (
    closer_copilot_fallback_lines,
    closer_copilot_prompt_addon,
    closer_meeting_suggestions_three,
    closer_show_moment_hint,
    closer_timed_replies_prompt_addon,
    compute_closer_stage,
    polish_timed_fallback_line,
)
from app.services.ai.conversation.last_message_signals import build_last_message_reply_context
from app.services.ai.conversation.conversation_stage_engine import detect_stage
from app.services.ai.conversation.dating_strategy_engine import plan_dating_strategy
from app.services.ai.conversation_coach import polish_many, polish_reply_quality
from app.services.ai.memory import (
    build_memory_context_for_prompt,
    delete_user_ai_memory,
    get_personalization_context,
    log_ai_event,
    update_user_ai_memory,
)
from app.services.learning.pattern_insights import (
    compute_live_pattern_insights,
    get_pattern_actions_state,
    get_pattern_insights_weekly,
    upsert_pattern_actions_state,
)
from app.schemas.ai_wingman import (
    GenerateRepliesRequest,
    AnalyzeConversationRequest,
    InterestStageResponse,
    TimingEngineRequest,
    TimingEngineResponse,
    TimingDecisionRequest,
    TimingDecisionResponse,
    ComboRequest,
    ComboResponse,
    TimedRepliesRequest,
    TimedRepliesResponse,
    MeetingReadinessRequest,
    MeetingReadinessResponse,
    MeetingReadyResponse,
    MeetingOptionsRequest,
    MeetingOptionsResponse,
    StallDetectionResponse,
    StartStrategyRequest,
    StartStrategyResponse,
    NextStepRequest,
    ImproveReplyRequest,
    GenerateOpenersRequest,
    ReplyOptionsRequest,
    ReplyOptionsResponse,
    BioSuggestRequest,
    GenerateOpenerSuggestionsRequest,
    GenerateOpenerSuggestionsResponse,
    ReadinessScoreRequest,
    ReadinessScoreResponse,
    CoachRequest,
    CoachResponse,
    EscalationReadinessRequest,
    EscalationReadinessResponse,
    RecoveryRequest,
    RecoveryResponse,
    CompatibilityScoreRequest,
    CompatibilityScoreResponse,
    CompatibilityScoreBatchRequest,
    CompatibilityScoreBatchResponse,
    ChatCopilotRequest,
    ChatCopilotResponse,
    ConversationQualityRequest,
    ConversationQualityResponse,
)
from app.services.ai.centralized import normalize_triplet, fallback_reply_triplet

router = APIRouter()


def _today_utc() -> str:
    return datetime.now(UTC).date().isoformat()


def _daily_boosts_get(db: Session, *, user_id: int) -> dict:
    """Daily boost + streak state (shared with /daily/boosts)."""
    return get_daily_boosts_state(db, user_id=int(user_id))


def _daily_boosts_consume(db: Session, *, user_id: int, boost_type: str) -> None:
    consume_daily_boost_slot(db, user_id=int(user_id), boost_type=str(boost_type or ""))


def _conversation_meta_key(viewer_user_id: int, partner_user_id: int | None) -> str:
    """Redis key for per-thread lightweight metadata."""
    if not partner_user_id:
        return f"conversation:meta:{int(viewer_user_id)}:none"
    a, b = sorted([int(viewer_user_id), int(partner_user_id)])
    return f"conversation:meta:{a}:{b}"


def _store_meeting_stage(
    db: Session,
    viewer_user_id: int,
    partner_user_id: int | None,
    stage: str,
    confidence: int,
    suggest_action: str,
) -> None:
    """
    Store result as conversation.meta.stage (best-effort).
    This project currently has no dedicated Conversation table, so we persist it in Redis.
    """
    try:
        r = get_redis()
    except Exception:
        r = None
    if r is not None:
        try:
            key = _conversation_meta_key(viewer_user_id, partner_user_id)
            r.hset(
                key,
                mapping={
                    "stage": str(stage),
                    "confidence": str(int(confidence)),
                    "suggest_action": str(suggest_action),
                    "updated_at": datetime.now(UTC).isoformat(),
                },
            )
            # Keep it warm for a day; refreshed on new analysis.
            r.expire(key, 60 * 60 * 24)
        except Exception:
            pass
    try:
        track_event(
            db,
            "ai_meeting_engine_stage_saved",
            user_id=int(viewer_user_id),
            payload={
                "partner_user_id": int(partner_user_id) if partner_user_id else None,
                "stage": str(stage),
                "confidence": int(confidence),
                "suggest_action": str(suggest_action),
            },
        )
    except Exception:
        pass


def _meeting_prompt_cooldown_ok(viewer_user_id: int, partner_user_id: int, *, cooldown_days: int = 7) -> bool:
    """Best-effort server-side cooldown for meeting prompts (per pair)."""
    try:
        r = get_redis()
    except Exception:
        r = None
    if r is None:
        return True
    try:
        key = _conversation_meta_key(int(viewer_user_id), int(partner_user_id))
        raw = r.hget(key, "meeting_prompt_shown_at")
        if not raw:
            return True
        s = str(raw.decode("utf-8") if hasattr(raw, "decode") else raw).strip()
        if not s:
            return True
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        dt = dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        age = datetime.now(UTC) - dt
        return age.total_seconds() >= float(cooldown_days) * 86400.0
    except Exception:
        return True


def _mark_meeting_prompt_shown(viewer_user_id: int, partner_user_id: int) -> None:
    try:
        r = get_redis()
    except Exception:
        r = None
    if r is None:
        return
    try:
        key = _conversation_meta_key(int(viewer_user_id), int(partner_user_id))
        r.hset(key, mapping={"meeting_prompt_shown_at": datetime.now(UTC).isoformat()})
        r.expire(key, 60 * 60 * 24 * 8)
    except Exception:
        return


def _age_from_profile(profile: Profile | None) -> int | None:
    if not profile:
        return None
    try:
        dob = getattr(profile, "date_of_birth", None)
        if dob:
            from datetime import date

            d = dob if isinstance(dob, date) else None
            if d:
                today = datetime.now(UTC).date()
                years = today.year - d.year
                if (today.month, today.day) < (d.month, d.day):
                    years -= 1
                return int(years)
    except Exception:
        pass
    try:
        a = getattr(profile, "age", None)
        if a is None:
            return None
        ia = int(a)
        return ia if ia > 0 else None
    except Exception:
        return None


def _positive_tone_score(texts: list[str]) -> float:
    joined = " ".join(texts).lower()
    if not joined.strip():
        return 0.0
    emoji = any(ch in joined for ch in ["🙂", "😊", "😄", "😂", "❤️", "😍", "😉", "✨"])
    pos_words = sum(
        1
        for w in [
            "love",
            "like",
            "nice",
            "fun",
            "cute",
            "haha",
            "lol",
            "клас",
            "круто",
            "подобається",
            "приємно",
            "супер",
        ]
        if w in joined
    )
    score = 0.35 * (1.0 if emoji else 0.0) + 0.65 * min(1.0, pos_words / 3.0)
    return max(0.0, min(1.0, float(score)))


def _meeting_templates(locale: str, *, city: str | None = None) -> list[dict]:
    """Deterministic one-sentence meeting drafts. Always end with a question."""
    loc = (locale or "en").strip().lower()
    c = (city or "").strip()
    near = (
        f"in {c}"
        if loc == "en" and c
        else (f"у {c}" if loc == "uk" and c else (f"в {c}" if loc == "ru" and c else (f"en {c}" if loc == "es" and c else "")))
    )
    near_part = f" {near}" if near else ""
    if loc == "uk":
        return [
            {"kind": "coffee", "label": "Coffee", "text": f"Мені подобається, як легко ми спілкуємось 🙂 може якось вип’ємо кави{near_part}?"},
            {"kind": "walk", "label": "Walk", "text": f"Мені подобається наш вайб 🙂 може якось прогуляємось{near_part}?"},
            {"kind": "drinks", "label": "Drinks", "text": f"З тобою реально приємно 🙂 може якось вип’ємо щось{near_part}?"},
        ]
    if loc == "ru":
        return [
            {"kind": "coffee", "label": "Coffee", "text": f"Мне нравится, как легко у нас идёт разговор 🙂 может как-нибудь выпьем кофе{near_part}?"},
            {"kind": "walk", "label": "Walk", "text": f"С тобой очень легко 🙂 может как-нибудь прогуляемся{near_part}?"},
            {"kind": "drinks", "label": "Drinks", "text": f"Мне нравится наш вайб 🙂 может как-нибудь выпьем что-то{near_part}?"},
        ]
    if loc == "es":
        return [
            {"kind": "coffee", "label": "Coffee", "text": f"Me gusta lo fácil que se siente este chat 🙂 ¿te apetece tomar un café{near_part}?"},
            {"kind": "walk", "label": "Walk", "text": f"Me gusta nuestro vibe 🙂 ¿te apetece dar un paseo{near_part}?"},
            {"kind": "drinks", "label": "Drinks", "text": f"Me gusta esta energía 🙂 ¿te apetece tomar algo{near_part}?"},
        ]
    return [
        {"kind": "coffee", "label": "Coffee", "text": f"I like how easy this chat feels 🙂 want to grab coffee{near_part} sometime?"},
        {"kind": "walk", "label": "Walk", "text": f"I like our vibe 🙂 want to go for a walk{near_part} sometime?"},
        {"kind": "drinks", "label": "Drinks", "text": f"This feels easy 🙂 want to grab drinks{near_part} sometime?"},
    ]

def _sanitize(text: str, max_len: int) -> str:
    """Local helper because chat_safety.sanitize_user_text() doesn't take length."""
    s = sanitize_user_text(text or "")
    if not s:
        return ""
    if len(s) > int(max_len):
        return s[: int(max_len)].rstrip() + "…"
    return s


def _display_name(db: Session, user_id: int) -> str:
    p = db.query(Profile).filter(Profile.user_id == int(user_id)).first()
    if not p:
        return ""
    return _sanitize(str(getattr(p, "display_name", "") or ""), 80)


def _last_partner_message_plain(db: Session, *, me_user_id: int, partner_user_id: int) -> str:
    """Last plain-text message the partner sent to the current user (for contextual fallbacks)."""
    row = (
        db.query(Message)
        .filter(Message.sender_id == int(partner_user_id), Message.receiver_id == int(me_user_id))
        .order_by(Message.created_at.desc())
        .first()
    )
    if not row:
        return ""
    return str(getattr(row, "content", "") or "").strip()


def _guard_uk_chat_brain_response_variants(lang: str | None, variants: dict[str, str] | None, partner_plain: str) -> dict[str, str]:
    """Strip English leakage from Gemini/topic fallbacks for Ukrainian UI."""
    base = {k: str((variants or {}).get(k) or "").strip() for k in ("light", "flirty", "deep")}
    if normalize_chat_ai_locale(lang or "en") != "uk":
        return base
    from app.services.ai.conversation.contextual_fallback_triples import guard_uk_variant_pack

    return guard_uk_variant_pack(base, last_partner_message=partner_plain)


def _emoji_level(text: str) -> float:
    # rough heuristic: fraction of chars that are emoji-like or emoticons
    s = text or ""
    if not s:
        return 0.0
    # include common emoji range + a few symbols
    emoji_count = sum(1 for ch in s if ord(ch) >= 0x1F300) + s.count("🙂") + s.count("😉") + s.count("😂") + s.count("😄") + s.count("❤️")
    return max(0.0, min(1.0, float(emoji_count) / max(1.0, float(len(s)) / 12.0)))


def _median(nums: list[float]) -> float | None:
    if not nums:
        return None
    xs = sorted(float(x) for x in nums)
    n = len(xs)
    mid = n // 2
    if n % 2 == 1:
        return xs[mid]
    return 0.5 * (xs[mid - 1] + xs[mid])


def _conversation_quality_from_messages(messages: list[dict]) -> tuple[int, str]:
    """
    Compute a deterministic conversation-quality score.

    Requested metrics:
    - reply time (median seconds on turn-switches, best-effort if timestamps exist)
    - message length (avg chars)
    - questions count (count of '?' in last 20 messages)
    - engagement ratio (min(msg_count_me, msg_count_them)/max(...))
    """
    tail = list(messages or [])[-20:]

    norm: list[dict] = []
    for m in tail:
        if not isinstance(m, dict):
            continue
        role = str(m.get("role") or "").strip().lower()
        role = "me" if role == "me" else "them" if role == "them" else ""
        text = str(m.get("text") or m.get("message") or "").strip()
        ts_ms = m.get("ts_ms", None)
        try:
            ts_ms_int = int(ts_ms) if ts_ms is not None else None
        except Exception:
            ts_ms_int = None
        if not role or not text:
            continue
        norm.append({"role": role, "text": text, "ts_ms": ts_ms_int})

    if not norm:
        return 0, "cold"

    # engagement ratio
    me_cnt = sum(1 for m in norm if m["role"] == "me")
    them_cnt = sum(1 for m in norm if m["role"] == "them")
    denom = max(me_cnt, them_cnt, 1)
    engagement_ratio = min(me_cnt, them_cnt) / float(denom)

    # message length (chars)
    avg_len = sum(len(m["text"]) for m in norm) / float(len(norm))
    me_texts = [m["text"] for m in norm if m["role"] == "me"]
    them_texts = [m["text"] for m in norm if m["role"] == "them"]
    avg_len_me = (sum(len(t) for t in me_texts) / float(len(me_texts))) if me_texts else 0.0
    avg_len_them = (sum(len(t) for t in them_texts) / float(len(them_texts))) if them_texts else 0.0
    them_short_rate = (sum(1 for t in them_texts if len(t.strip()) <= 4) / float(len(them_texts))) if them_texts else 0.0

    # questions count
    questions = sum(1 for m in norm if "?" in m["text"])
    q_rate = questions / float(len(norm))

    # reply time (median seconds when role flips and timestamps exist)
    deltas_s: list[float] = []
    for prev, cur in zip(norm, norm[1:]):
        if prev["role"] == cur["role"]:
            continue
        if prev["ts_ms"] is None or cur["ts_ms"] is None:
            continue
        dt = (int(cur["ts_ms"]) - int(prev["ts_ms"])) / 1000.0
        if dt < 0:
            continue
        # clamp absurd gaps; still count but cap influence
        deltas_s.append(min(dt, 24 * 3600.0))
    median_reply_s = _median(deltas_s)

    score = 50.0

    # reply time contribution
    if median_reply_s is None:
        score += 0.0
    elif median_reply_s <= 120:
        score += 15.0
    elif median_reply_s <= 600:
        score += 10.0
    elif median_reply_s <= 1800:
        score += 5.0
    elif median_reply_s <= 7200:
        score -= 5.0
    else:
        score -= 15.0

    # message length contribution
    if avg_len < 8:
        score -= 10.0
    elif avg_len < 20:
        score -= 3.0
    elif avg_len <= 140:
        score += 10.0
    elif avg_len <= 260:
        score += 3.0
    else:
        score -= 5.0

    # questions contribution
    if q_rate >= 0.35:
        score += 15.0
    elif q_rate >= 0.2:
        score += 10.0
    elif q_rate >= 0.1:
        score += 5.0
    else:
        score -= 5.0

    # low-effort penalty (dying chat): partner answers are ultra-short
    if them_texts:
        if them_short_rate >= 0.6:
            score -= 20.0
        elif avg_len_them > 0 and avg_len_them < 10:
            score -= 10.0

    # engagement ratio contribution
    if engagement_ratio >= 0.6:
        score += 15.0
    elif engagement_ratio >= 0.4:
        score += 10.0
    elif engagement_ratio >= 0.25:
        score += 5.0
    else:
        score -= 10.0

    score_i = int(max(0, min(100, round(score))))
    status = "cold"
    if score_i >= 75:
        status = "hot"
    elif score_i >= 45:
        status = "warm"
    return score_i, status


def _ewma(prev: float, value: float, alpha: float) -> float:
    return (1.0 - alpha) * float(prev) + alpha * float(value)


def _interest_stage_fallback(messages: list[str]) -> dict:
    texts = [str(m or "").strip() for m in (messages or []) if str(m or "").strip()]
    tail = texts[-12:]
    if not tail:
        return {"interest_score": 0, "stage": "cold", "mutuality_score": 0, "signals": ["no context"]}

    joined = " ".join(tail).lower()
    q_total = sum(1 for t in tail if "?" in t)
    short_cnt = sum(1 for t in tail[-4:] if len(t) <= 12)
    okish = sum(1 for token in ["ок", "окей", "норм", "ага", "мм", "ясно"] if token in joined)
    positive = sum(1 for token in ["круто", "клас", "супер", "😊", "🙂", "😉", "😄", "😂", "❤️"] if token in joined)

    # We can't reliably separate sides here (messages are plain strings), so mutuality is inferred
    # from question density + answer length stability.
    mutuality = 30 + min(40, 10 * q_total) - min(25, 10 * short_cnt) - min(20, 8 * okish) + min(15, 6 * positive)
    mutuality = max(0, min(100, int(mutuality)))

    interest = 25 + min(35, 6 * q_total) + min(20, 6 * positive) - min(25, 9 * short_cnt) - min(20, 8 * okish)
    interest = max(0, min(100, int(interest)))

    stage = "cold"
    if interest >= 80 and mutuality >= 70:
        stage = "ready"
    elif interest >= 60 and mutuality >= 50:
        stage = "engaged"
    elif interest >= 40:
        stage = "warming"

    signals: list[str] = []
    if q_total >= 2:
        signals.append("asks questions")
    if positive >= 1:
        signals.append("positive эмоції")
    if short_cnt >= 2 or okish >= 1:
        signals.append("короткі відповіді")
    if not signals:
        signals.append("neutral tone")

    return {"interest_score": interest, "stage": stage, "mutuality_score": mutuality, "signals": signals[:10]}


def _parse_dt_utc(value: str | None):
    if not value:
        return None
    s = str(value).strip()
    if not s:
        return None
    try:
        # Accept ISO8601; handle trailing Z.
        from datetime import datetime, UTC

        s2 = s.replace("Z", "+00:00")
        dt = datetime.fromisoformat(s2)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC)
    except Exception:
        return None


def _timing_engine_fallback(req: TimingEngineRequest) -> dict:
    from datetime import datetime, UTC

    now = datetime.now(UTC)
    last_dt = _parse_dt_utc(req.last_message_at)
    minutes_since = None
    if last_dt is not None:
        minutes_since = max(0.0, float((now - last_dt).total_seconds()) / 60.0)

    avg_reply = float(req.avg_partner_reply_minutes) if req.avg_partner_reply_minutes is not None else 45.0
    avg_reply = max(5.0, min(24 * 60.0, avg_reply))

    active_hours = [int(h) for h in (req.partner_active_hours or []) if isinstance(h, int) or str(h).isdigit()]
    active_hours = [h for h in active_hours if 0 <= int(h) <= 23]
    active_hours = list(dict.fromkeys([int(h) for h in active_hours]))[:24]

    stage = (req.interest_stage or "").strip().lower()
    mutuality = int(req.mutuality_score or 0)
    stall = int(req.stall_score or 0) if req.stall_score is not None else 0

    # Determine if the last message is from "me" (to avoid double-text spam).
    last_role = None
    try:
        if req.messages:
            m = req.messages[-1]
            if isinstance(m, dict):
                last_role = str(m.get("role") or "").strip().lower() or None
    except Exception:
        last_role = None

    # Re-engage after 12–48h silence.
    if minutes_since is not None and minutes_since >= 12 * 60 and minutes_since <= 48 * 60:
        window = ""
        if active_hours:
            window = f"today {min(active_hours):02d}:00-{max(active_hours):02d}:00"
        return {
            "should_send_now": bool(now.hour in active_hours) if active_hours else True,
            "confidence": 78,
            "nudge_type": "reengage",
            "best_time_window": window,
            "reasoning": "Довга пауза — краще м’яко перезапустити розмову без тиску.",
        }

    # Wait if you just sent something recently.
    if last_role == "me" and minutes_since is not None and minutes_since < 25:
        return {
            "should_send_now": False,
            "confidence": 85,
            "nudge_type": "wait",
            "best_time_window": "in 30-60 min",
            "reasoning": "Ти щойно написав(ла) — краще не дублювати повідомлення так швидко.",
        }

    # If stalled, prefer revive.
    if stall >= 65 and stage in {"cold", "warming"}:
        return {
            "should_send_now": True,
            "confidence": 70,
            "nudge_type": "revive",
            "best_time_window": "",
            "reasoning": "Розмова просідає — варто зробити новий хід з іншою темою.",
        }

    hour_ok = (now.hour in active_hours) if active_hours else True
    window_passed = (minutes_since is None) or (minutes_since >= avg_reply)
    engaged = stage in {"engaged", "ready"} and mutuality >= 55

    if hour_ok and window_passed and engaged:
        window = ""
        if active_hours:
            window = f"today {min(active_hours):02d}:00-{max(active_hours):02d}:00"
        return {
            "should_send_now": True,
            "confidence": 80,
            "nudge_type": "now",
            "best_time_window": window,
            "reasoning": "Зараз хороший час: партнер зазвичай активний(а), пауза нормальна, і є взаємний інтерес.",
        }

    # Default: wait for their active window.
    window = ""
    if active_hours:
        window = f"today {min(active_hours):02d}:00-{max(active_hours):02d}:00"
    return {
        "should_send_now": False,
        "confidence": 66,
        "nudge_type": "wait",
        "best_time_window": window or "later today",
        "reasoning": "Краще трохи почекати і написати у вікно активності, щоб не виглядало як спам.",
    }


def _closer_stage_for_timed_replies_chat(chat: list[dict], *, hours_since_last: float | None) -> str:
    stall = _detect_stall_fallback(chat or [], hours_since_last=hours_since_last)
    cs, _ = compute_closer_stage(chat or [], stalled_chat=bool(stall.get("is_stalled")))
    return cs


def _timed_replies_fallback(
    chat: list[dict],
    *,
    nudge_type: str,
    locale: str | None = None,
    closer_stage: str | None = None,
) -> tuple[list[dict], str]:
    """Return (rows, source_locale_for_i18n). ``source`` matches ``normalize_ai_request_locale`` when no translate needed."""
    from app.services.ai.ai_fallback_phrases import timed_rows_for_nudge

    loc_ai = normalize_ai_request_locale(locale or "en")
    n = (nudge_type or "").strip().lower()
    if n == "wait":
        return [], loc_ai

    if n in {"reengage", "revive"}:
        rows, src = timed_rows_for_nudge(n, loc_ai)
        for r in rows:
            r["text"] = _ensure_question_short(str(r.get("text") or ""))
        return rows, src

    last_in = ""
    for m in reversed(chat or []):
        if m.get("role") == "them":
            last_in = str(m.get("text") or "").strip()
            break
    ctx = [str(x.get("text") or "").strip() for x in (chat or [])[-10:] if str(x.get("text") or "").strip()]
    lm = last_in or (ctx[-1] if ctx else "")
    cs_arg = (closer_stage or "").strip().lower()

    if cs_arg:
        lines = closer_copilot_fallback_lines(loc_ai, cs_arg, lm, continue_mode=True)
        return [
            {"style": "light", "text": polish_timed_fallback_line(lines[0], closer_stage=cs_arg)},
            {"style": "flirty", "text": polish_timed_fallback_line(lines[1], closer_stage=cs_arg)},
            {"style": "deep", "text": polish_timed_fallback_line(lines[2], closer_stage=cs_arg)},
        ], loc_ai

    if n not in {"reengage", "revive"} and loc_ai == "uk":
        from app.services.ai.conversation.contextual_fallback_triples import uk_reply_fallback_three_lines

        lines = uk_reply_fallback_three_lines(lm, continue_mode=True)
        return [
            {"style": "light", "text": _ensure_question_short(lines[0])},
            {"style": "flirty", "text": _ensure_question_short(lines[1])},
            {"style": "deep", "text": _ensure_question_short(lines[2])},
        ], "uk"

    base = ReplyGenerator.generate_replies(
        lm,
        conversation_context=ctx,
        user_style="chill",
        allow_edgy_mode=False,
        locale=loc_ai,
    )
    from app.services.ai.ai_fallback_phrases import timed_now_emergency_triple

    d_light, d_flirty, d_deep = timed_now_emergency_triple(loc_ai)

    light = _ensure_question_short(str((base[0] or {}).get("text") or d_light))
    flirty = _ensure_question_short(str((base[1] or {}).get("text") or d_flirty))
    deep = _ensure_question_short(str((base[2] or {}).get("text") or d_deep))

    return [
        {"style": "light", "text": light},
        {"style": "flirty", "text": flirty},
        {"style": "deep", "text": deep},
    ], loc_ai


async def _timed_replies_fallback_i18n(
    chat: list[dict],
    *,
    nudge_type: str,
    locale: str | None = None,
    closer_stage: str | None = None,
) -> list[dict]:
    from app.services.ai.ai_fallback_phrases import timed_now_emergency_triple
    from app.services.ai.locale_rewrite import batch_translate_lines, enforce_text_locale
    from app.services.ai.output_script_locale import text_matches_requested_locale

    rows, src = _timed_replies_fallback(chat, nudge_type=nudge_type, locale=locale, closer_stage=closer_stage)
    loc = normalize_ai_request_locale(locale)
    if not rows:
        return rows

    if loc != src:
        texts = [str(r.get("text") or "") for r in rows]
        try:
            tr = await batch_translate_lines(texts, loc)
            if len(tr) == len(rows) and all((x or "").strip() for x in tr):
                for i, r in enumerate(rows):
                    r["text"] = tr[i]
        except Exception:
            pass

    emergency = timed_now_emergency_triple(loc)
    for i, r in enumerate(rows):
        t = str(r.get("text") or "").strip()
        if t and text_matches_requested_locale(t, loc):
            continue
        try:
            fixed = await enforce_text_locale(t, loc)
        except Exception:
            fixed = t
        if fixed and text_matches_requested_locale(fixed, loc):
            r["text"] = polish_timed_fallback_line(fixed, closer_stage=closer_stage)
        else:
            r["text"] = polish_timed_fallback_line(emergency[min(i, 2)], closer_stage=closer_stage)
    if loc == "uk":
        from app.services.ai.conversation.contextual_fallback_triples import (
            uk_reply_fallback_three_lines,
            uk_suggestion_line_has_english_leak,
        )

        last_in_fb = ""
        for m in reversed(chat or []):
            if m.get("role") == "them":
                last_in_fb = str(m.get("text") or "").strip()
                break
        trip = uk_reply_fallback_three_lines(last_in_fb, continue_mode=True)
        for i, r in enumerate(rows):
            t = str(r.get("text") or "").strip()
            if uk_suggestion_line_has_english_leak(t):
                r["text"] = _ensure_question_short(trip[min(i, 2)])
    return rows


def _avg_partner_reply_minutes(rows: list[Message], *, viewer_id: int, partner_id: int) -> float | None:
    """
    Average time from viewer message -> next partner reply.
    Best-effort for timing nudges; ignore missing/invalid timestamps.
    """
    # Build list of (viewer_sent_at, partner_reply_at)
    pairs: list[float] = []
    last_viewer_at = None
    for m in rows:
        dt = getattr(m, "created_at", None)
        if dt is None:
            continue
        if getattr(dt, "tzinfo", None) is None:
            from datetime import UTC

            dt = dt.replace(tzinfo=UTC)
        if int(m.sender_id) == int(viewer_id):
            last_viewer_at = dt
        elif int(m.sender_id) == int(partner_id) and last_viewer_at is not None:
            diff_min = max(0.0, float((dt - last_viewer_at).total_seconds()) / 60.0)
            # Skip absurd diffs (clock issues / very long gaps) for "average reply time"
            if 0.0 <= diff_min <= 60.0 * 24.0 * 7.0:
                pairs.append(diff_min)
            last_viewer_at = None
    if not pairs:
        return None
    # Robust average: trim top/bottom 10% if enough samples.
    xs = sorted(pairs)
    if len(xs) >= 10:
        k = max(1, int(len(xs) * 0.1))
        xs = xs[k:-k] or xs
    return float(sum(xs)) / float(len(xs))


def _partner_active_hours(rows: list[Message], *, partner_id: int) -> list[int]:
    # Top hours of partner messages (UTC hours).
    from collections import Counter

    hours: list[int] = []
    for m in rows:
        if int(m.sender_id) != int(partner_id):
            continue
        dt = getattr(m, "created_at", None)
        if dt is None:
            continue
        if getattr(dt, "tzinfo", None) is None:
            from datetime import UTC

            dt = dt.replace(tzinfo=UTC)
        hours.append(int(dt.hour))
    if not hours:
        return []
    c = Counter(hours)
    return [h for (h, _cnt) in c.most_common(6)]


def _combo_ui(nudge_type: str, *, stage: str, mutuality: int, stall_score: int) -> dict:
    n = (nudge_type or "").strip().lower()
    if n == "now":
        return {"title": "🟢 Краще написати зараз", "reason": "Є взаємність і розмова тримається — хороший момент написати."}
    if n == "reengage":
        return {"title": "🔁 Можна повернути розмову", "reason": "Є пауза — м’який перезапуск без тиску виглядатиме природно."}
    if n == "revive":
        return {"title": "💬 Розмова просідає — змініть хід", "reason": "Краще зайти з нової теми або легкого жарту, щоб повернути енергію."}
    # wait
    if stage in {"engaged", "ready"} and mutuality >= 60 and stall_score < 65:
        return {"title": "🕒 Краще зачекати", "reason": "Момент непоганий, але краще не поспішати, щоб не виглядало як спам."}
    return {"title": "🕒 Краще зачекати", "reason": "Краще дати людині час і написати пізніше у вікно активності."}


def _meeting_readiness_fallback(messages: list[str]) -> dict:
    texts = [str(m or "").strip() for m in (messages or []) if str(m or "").strip()]
    tail = texts[-10:]
    if not tail:
        return {"meeting_readiness": 10, "reasoning": ["no context"], "risk_level": "high"}

    joined = " ".join(tail).lower()
    q = sum(1 for t in tail if "?" in t)
    positive = sum(1 for token in ["круто", "клас", "супер", "😊", "🙂", "😉", "😄", "😂", "❤️"] if token in joined)
    cold = sum(1 for token in ["ок", "ага", "мм", "норм", "ясно", "не знаю"] if token in joined)

    score = 25 + min(35, 5 * max(0, len(tail) - 2)) + min(20, 6 * q) + min(15, 5 * positive) - min(20, 6 * cold)
    score = max(0, min(100, int(score)))

    reasoning: list[str] = []
    if len(tail) >= 6:
        reasoning.append("active conversation")
    if q >= 2:
        reasoning.append("asks questions")
    if positive >= 1:
        reasoning.append("good energy")
    if not reasoning:
        reasoning.append("limited signals")

    risk_level = "low" if score >= 70 else "medium" if score >= 45 else "high"
    return {"meeting_readiness": score, "reasoning": reasoning[:6], "risk_level": risk_level}


def _meeting_options_fallback(*, readiness: int) -> dict:
    if readiness < 60:
        return {"meeting_options": []}
    if readiness >= 80:
        return {
            "meeting_options": [
                "До речі, є ідея: можемо якось на днях вирватися на каву або коротку прогулянку в людному місці — як тобі така думка?",
                "Мені з тобою легко спілкуватися 🙂 Може, перенесемо це в офлайн: кава/прогулянка десь у центрі цими днями?",
            ][:3]
        }
    # 60–80
    return {
        "meeting_options": [
            "Якщо захочеш, можемо якось обережно познайомитися вживу — кава або коротка прогулянка в публічному місці, без поспіху 🙂 Як тобі?",
            "До речі, якщо буде комфортно, можемо якось на каву — в людному місці й на коротко 🙂 Підійде тобі такий формат?",
        ][:3]
    }


def _detect_stall_fallback(chat: list[dict], *, hours_since_last: float | None) -> dict:
    # Heuristic signals:
    # - short replies like "ок", "норм"
    # - no questions
    # - 12–24h pause
    tail = [str((m or {}).get("text") or "").strip() for m in (chat or [])[-6:] if str((m or {}).get("text") or "").strip()]
    if not tail:
        return {"is_stalled": False, "stall_score": 0, "reasons": []}

    joined = " ".join(tail).lower()
    short_cnt = sum(1 for t in tail[-3:] if len(t) <= 12)
    okish = sum(1 for token in ["ок", "окей", "норм", "ага", "мм", "ясно"] if token in joined)
    q = sum(1 for t in tail[-4:] if "?" in t)
    emoji = sum(1 for token in ["🙂", "😉", "😄", "😂", "❤️"] if token in joined)

    score = 15 + 22 * short_cnt + 14 * okish + (18 if q == 0 else 0) - (8 if emoji >= 1 else 0)
    if hours_since_last is not None and hours_since_last >= 12:
        score += 25
    score = max(0, min(100, int(score)))

    reasons: list[str] = []
    if short_cnt >= 2 or okish >= 1:
        reasons.append("short replies")
    if q == 0:
        reasons.append("no questions")
    if hours_since_last is not None and hours_since_last >= 12:
        reasons.append("long pause")
    if emoji == 0 and score >= 60:
        reasons.append("neutral/cold tone")

    return {"is_stalled": score >= 65, "stall_score": score, "reasons": reasons[:6]}


def _revive_fallback(_chat: list[dict], *, locale: str | None = None) -> list[dict]:
    """Deterministic revive rows for copilot stall path — fully localized via phrase bank."""
    loc = normalize_ai_request_locale(locale or "en")
    light, flirty, deep = timed_revive_triple(loc)
    return [
        {"label": "Topic shift", "style": "light", "text": _ensure_question_short(light)},
        {"label": "Playful", "style": "flirty", "text": _ensure_question_short(flirty)},
        {"label": "Go deeper", "style": "deep", "text": _ensure_question_short(deep)},
    ]


def _opener_style_label(style: str) -> str:
    key = (style or "").strip().lower()
    if key in {"flirty", "флірт"}:
        return "flirty"
    if key in {"curious", "цікаво", "цікавий"}:
        return "curious"
    return "light"


def _start_strategy_fallback(*, partner_profile: Profile | None, partner_name: str, locale: str | None) -> dict:
    """Deterministic fallback: same locale coverage as phrase banks, exactly three openers."""
    from app.services.app_language import normalize_app_language

    lang = normalize_app_language(locale or "en")
    city = (getattr(partner_profile, "city", "") or "").strip() if partner_profile else ""
    hooks: list[str] = []
    if (partner_name or "").strip():
        hooks.append("has_name")
    if city:
        hooks.append("city")
    wait_reason = start_strategy_wait_reason(lang)
    typed = opener_typed_fallback(lang)
    openers = [
        {"style": "light", "text": _ensure_question_short(str(typed[0][1]))},
        {"style": "flirty", "text": _ensure_question_short(str(typed[1][1]))},
        {"style": "curious", "text": _ensure_question_short(str(typed[2][1]))},
    ]
    return {
        "strategy": wait_reason,
        "confidence": None,
        "hooks": hooks[:3],
        "openers": openers,
    }


@router.post("/start-strategy", response_model=StartStrategyResponse)
async def start_strategy(
    req: StartStrategyRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    partner_user_id = int(req.partner_user_id)
    if is_blocked(db, current_user.id, partner_user_id):
        raise HTTPException(status_code=403, detail=api_error("chat.user_blocked"))
    if not users_are_matched(db, current_user.id, partner_user_id):
        raise HTTPException(status_code=403, detail=api_error("chat.match_required"))

    plan = SubscriptionService().get_active_plan(db, current_user.id)
    is_premium = plan in {"premium", "premium_plus"}
    tier = "premium" if is_premium else "free"

    try:
        enforce_ai_limits(db, current_user.id)
    except RateLimitExceeded:
        partner_profile = db.query(Profile).filter(Profile.user_id == partner_user_id).first()
        partner_name = _sanitize(getattr(partner_profile, "display_name", "") or "", 80)
        track_event(db, "ai_start_strategy_requested", user_id=current_user.id, payload={"tier": tier, "limited": True, "partner_user_id": partner_user_id})
        requested = getattr(req, "language", None) or req.locale or "en"
        return _start_strategy_fallback(partner_profile=partner_profile, partner_name=partner_name, locale=str(requested))

    my_profile = db.query(Profile).filter(Profile.user_id == current_user.id).first()
    partner_profile = db.query(Profile).filter(Profile.user_id == partner_user_id).first()
    partner_name = _sanitize(getattr(partner_profile, "display_name", "") or "", 80)

    # Logging
    logger.info("ai_start_strategy_requested", extra={"tier": tier, "partner_user_id": partner_user_id})
    track_event(db, "ai_start_strategy_requested", user_id=current_user.id, payload={"tier": tier, "partner_user_id": partner_user_id})

    if not is_premium:
        return _start_strategy_fallback(partner_profile=partner_profile, partner_name=partner_name, locale=req.locale)

    if not settings.ENABLE_AI_SUGGESTIONS or settings.AI_PROVIDER != "gemini" or not (settings.GEMINI_API_KEY or "").strip():
        return _start_strategy_fallback(partner_profile=partner_profile, partner_name=partner_name, locale=req.locale)

    from app.services.app_language import normalize_app_language

    # CRITICAL: UI language must override profile.preferred_language.
    requested = getattr(req, "language", None) or req.locale or "en"
    locale = normalize_app_language(str(requested))
    user_ctx = _profile_context(my_profile)
    partner_ctx = _profile_context(partner_profile)
    photo_ctx_note = "If photo captions/tags exist, use them. If not, do NOT invent photo details."

    lang_name = english_language_name_for_ai_prompt(locale)
    system = (
        "You are NEYRA AI.\n"
        "Goal: Before the first message, analyze partner profile and suggest the best conversation opener strategy.\n"
        f"CRITICAL LANGUAGE RULE: Respond ONLY in {lang_name} (locale tag: {locale}). Do NOT use any other language. Do not mix languages.\n"
        "Output STRICT JSON exactly matching:\n"
        "{\n"
        '  "strategy": "short explanation of the best angle",\n'
        '  "confidence": 0-100,\n'
        '  "hooks": ["travel","humor","shared interests"],\n'
        '  "openers": [\n'
        '    {"style":"light","text":"..."},\n'
        '    {"style":"flirty","text":"..."},\n'
        '    {"style":"curious","text":"..."}\n'
        "  ]\n"
        "}\n"
        "Hard rules:\n"
        "- Generate exactly 3 openers.\n"
        "- All openers must be clearly different (tone + wording + structure).\n"
        "- Each opener must be 1–2 sentences and MUST end with a question.\n"
        "- Natural language, no cringe pickup lines.\n"
        "- No sexual content. No manipulation. No pressure.\n"
        "- Do NOT invent facts not present in profile/chat/photo tags.\n"
        "- Use safe casual tone.\n"
    )

    mem_ctx = build_memory_context_for_prompt(db, user_id=current_user.id, partner_user_id=partner_user_id) if is_premium else {}
    payload = {
        "locale": locale,
        "language": locale,
        "tier": tier,
        "user_profile": user_ctx,
        "partner_profile": partner_ctx,
        "memory": mem_ctx.get("AI_MEMORY") if isinstance(mem_ctx, dict) else {},
        "notes": photo_ctx_note,
        "thread_messages": [_sanitize(x, 400) for x in (req.messages or [])][:3],
    }

    try:
        client = GeminiClient()
        # Cyrillic guard: if English requested but output contains Cyrillic, retry up to 2 then fallback.
        out = None
        for attempt in range(3):
            out = await client.generate_json(
                system_prompt=system,
                user_prompt=f"INPUT_JSON:\n{payload}",
                temperature=0.7,
                max_output_tokens=520,
                model=settings.GEMINI_CHAT_MODEL,
            )
            if not isinstance(out, dict):
                break
            try:
                # Detect script from opener texts (cheap, robust for en vs uk/ru).
                texts = []
                for row in (out.get("openers") or [])[:3]:
                    if isinstance(row, dict):
                        texts.append(str(row.get("text") or ""))
                joined = " ".join(texts)
                has_cyr = any("\u0400" <= ch <= "\u04FF" for ch in joined)
                detected_script = "cyrillic" if has_cyr else "latin"
                logger.info(
                    "start_strategy_lang_check",
                    extra={"event": "start_strategy_lang_check", "requested": locale, "detected_script": detected_script, "attempt": attempt + 1},
                )
                if locale == "en" and has_cyr:
                    if attempt < 2:
                        continue
                    out = None
                break
            except Exception:
                break
        if not isinstance(out, dict):
            return _start_strategy_fallback(partner_profile=partner_profile, partner_name=partner_name, locale=locale)
        strategy = str(out.get("strategy") or "").strip() or None
        try:
            conf = int(out.get("confidence"))
            conf = max(0, min(100, conf))
        except Exception:
            conf = None
        hooks_raw = out.get("hooks") if isinstance(out.get("hooks"), list) else []
        hooks = [str(h or "").strip() for h in hooks_raw if str(h or "").strip()][:6]
        openers_raw = out.get("openers") if isinstance(out.get("openers"), list) else []
        openers: list[dict] = []
        for row in openers_raw[:3]:
            if not isinstance(row, dict):
                continue
            style = _opener_style_label(str(row.get("style") or "light"))
            text = _ensure_question_short(str(row.get("text") or ""))
            if not text:
                continue
            openers.append({"style": style, "text": text})
        # Enforce locale (drop any drift).
        try:
            from app.services.ai.locale import is_text_locale as _is_text_locale

            openers = [o for o in openers if _is_text_locale(o.get("text") or "", locale)]
        except Exception:
            pass
        # Ensure exactly 3 and diverse-ish; otherwise fallback to safe filtered openers.
        texts = [o["text"] for o in openers]
        if len(openers) != 3 or _diversity_score(texts) < 0.12:
            typed_fb = opener_typed_fallback(locale)
            openers = [
                {"style": "light", "text": _ensure_question_short(str(typed_fb[0][1]))},
                {"style": "flirty", "text": _ensure_question_short(str(typed_fb[1][1]))},
                {"style": "curious", "text": _ensure_question_short(str(typed_fb[2][1]))},
            ]
        track_event(
            db,
            "ai_start_strategy_generated",
            user_id=current_user.id,
            payload={"tier": tier, "hooks_count": len(hooks), "openers_count": len(openers), "partner_user_id": partner_user_id},
        )
        return {"strategy": strategy, "confidence": conf, "hooks": hooks, "openers": openers}
    except GeminiError as e:
        set_last_provider_used("fallback")
        set_last_gemini_error(f"{e.code}: {e.message}")
        incr_fallback_24h()
        logger.warning("ai_fallback_used", extra={"endpoint": "start-strategy", "provider": "fallback", "reason": e.code})
        return _start_strategy_fallback(partner_profile=partner_profile, partner_name=partner_name, locale=locale)
    except Exception as e:
        set_last_provider_used("fallback")
        set_last_gemini_error(str(e))
        incr_fallback_24h()
        logger.exception("ai_fallback_used", extra={"endpoint": "start-strategy", "provider": "fallback", "reason": "exception"})
        return _start_strategy_fallback(partner_profile=partner_profile, partner_name=partner_name, locale=locale)


@router.post("/start-strategy/event")
def start_strategy_event(
    payload: dict = Body(default={}),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # Accept language/locale for debugging (do not affect event semantics).
    requested = str(payload.get("language") or payload.get("locale") or "").strip() or None
    name = str(payload.get("name") or "").strip()
    allowed = {"opener_shown", "opener_selected", "opener_sent", "opener_edited", "partner_replied"}
    if name not in allowed:
        raise HTTPException(status_code=400, detail="Invalid event name")
    partner_user_id = payload.get("partner_user_id")
    try:
        partner_user_id = int(partner_user_id) if partner_user_id is not None else None
    except Exception:
        partner_user_id = None
    style = str(payload.get("style") or "").strip().lower() or None
    edited = bool(payload.get("edited")) if name in {"opener_sent", "opener_edited"} else None
    track_event(
        db,
        "ai_start_strategy_event",
        user_id=current_user.id,
        payload={
            "name": name,
            "partner_user_id": partner_user_id,
            "style": style,
            "edited": edited,
            "partner_replied": bool(payload.get("partner_replied")) if name == "partner_replied" else None,
            "requested_language": requested,
        },
    )
    return {"ok": True}


@router.post("/dating-strategy")
def ai_dating_strategy(
    payload: dict = Body(default={}),
    _: User = Depends(get_current_user),
):
    """
    Coach-style next move from message list (no persistence).
    Optional: last_text_role, hours_since_last_text, trail_me, run_generation.
    """
    messages = payload.get("messages")
    if not isinstance(messages, list):
        messages = []
    stage_info = detect_stage(messages)
    hrs = payload.get("hours_since_last_text")
    try:
        hours_val = float(hrs) if hrs is not None else None
    except Exception:
        hours_val = None
    try:
        trail = int(payload.get("trail_me") or 0)
    except Exception:
        trail = 0
    ltr = payload.get("last_text_role")
    last_role = str(ltr).strip() if ltr is not None and str(ltr).strip() else None
    strat = plan_dating_strategy(
        stage_info=stage_info,
        stage_messages=messages,
        last_text_role=last_role,
        hours_since_last_text=hours_val,
        run_generation=bool(payload.get("run_generation", True)),
        trail_me=trail,
    )
    return {
        "next_action": strat.get("next_action"),
        "reasoning_tags": strat.get("reasoning_tags") or [],
        "relationship_stage": stage_info.get("stage"),
        "mutuality_score": stage_info.get("mutuality_score"),
        "energy_score": stage_info.get("energy_score"),
    }


@router.post("/conversation-stage")
def ai_conversation_stage(
    payload: dict = Body(default={}),
    _: User = Depends(get_current_user),
):
    """
    Privacy-safe: classify relationship stage from message metadata only (caller supplies text).
    No persistence. Use for client-side tone/strategy UX.
    """
    messages = payload.get("messages")
    if not isinstance(messages, list):
        messages = []
    return detect_stage(messages)


@router.get("/memory/context")
def ai_memory_context(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """
    Privacy-safe wingman memory (≤1KB JSON): tone_preference, interests, avoid, flirt_level, languages, notes.
    Available to all authenticated users — used to align AI suggestions without storing raw chat.
    """
    try:
        update_user_ai_memory(db, user_id=current_user.id)
    except Exception:
        pass
    ctx = get_personalization_context(db, user_id=current_user.id)
    summary = ctx.get("summary_json") if isinstance(ctx.get("summary_json"), dict) else {}
    try:
        raw = json.dumps(summary, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        byte_len = len(raw)
    except Exception:
        byte_len = 0
    return {
        "schema": "wingman_v1",
        "summary_json": summary,
        "updated_at": ctx.get("updated_at"),
        "byte_length": byte_len,
    }


@router.post("/memory/event")
def ai_memory_event(
    payload: dict = Body(default={}),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Append-only learning signal for wingman memory (option_selected, message_sent, partner_replied, etc.).
    Metadata must be aggregate-only — no raw message bodies (server sanitizes).
    """
    from app.services.ai.memory import ALLOWED_AI_MEMORY_EVENT_TYPES

    et = str(payload.get("event_type") or payload.get("type") or "").strip()
    if et not in ALLOWED_AI_MEMORY_EVENT_TYPES:
        raise HTTPException(status_code=400, detail=api_error("ai.invalid_event_type"))
    pid = payload.get("partner_user_id")
    try:
        partner_user_id = int(pid) if pid is not None and str(pid).strip() != "" else None
    except Exception:
        partner_user_id = None
    meta = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    if not meta and isinstance(payload.get("metadata_json"), dict):
        meta = payload.get("metadata_json") or {}
    if not meta and isinstance(payload.get("payload_json"), dict):
        meta = payload.get("payload_json") or {}
    thread_raw = payload.get("thread_id")
    thread_id = str(thread_raw).strip()[:64] if thread_raw is not None and str(thread_raw).strip() else None
    log_ai_event(
        db,
        user_id=int(current_user.id),
        partner_user_id=partner_user_id,
        event_type=et,
        metadata=meta if isinstance(meta, dict) else {},
        thread_id=thread_id,
    )
    try:
        update_user_ai_memory(db, user_id=int(current_user.id), partner_user_id=partner_user_id)
    except Exception:
        pass
    return {"ok": True}


@router.get("/memory/me")
def ai_memory_me(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    plan = SubscriptionService().get_active_plan(db, current_user.id)
    is_premium = plan in {"premium", "premium_plus"}
    if not is_premium:
        raise HTTPException(status_code=403, detail=api_error("chat.premium_required"))
    update_user_ai_memory(db, user_id=current_user.id)
    return build_memory_context_for_prompt(db, user_id=current_user.id, partner_user_id=None)


@router.delete("/memory/me")
def ai_memory_delete_me(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    # Allow delete for everyone (even free), but only premium has persistent rows.
    deleted = delete_user_ai_memory(db, user_id=current_user.id)
    return {"ok": True, "deleted": deleted}


@router.get("/insights/me")
def ai_insights_me(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """
    Pattern Insights (privacy-safe): precomputed aggregates + supportive suggestions.
    Available to all authenticated users.
    """
    weekly = get_pattern_insights_weekly(db, user_id=current_user.id)
    actions_state = get_pattern_actions_state(db, user_id=current_user.id)
    if not weekly or not (weekly.get("insights")):
        # On-demand fill so new users see useful content without waiting for the background worker.
        weekly = compute_live_pattern_insights(db, user_id=current_user.id, lookback_days=14)
    return {
        "insights": weekly.get("insights") or [],
        "aggregates": weekly.get("aggregates"),
        "generated_at": weekly.get("generated_at"),
        "actions_state": actions_state,
        "privacy": {
            "note": "NEYRA stores counts and patterns only — not your message text.",
        },
    }


@router.post("/insights/actions")
def ai_insights_actions(
    payload: dict = Body(default={}),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    insight_id = str(payload.get("insight_id") or "").strip()
    action_id = str(payload.get("action_id") or "").strip()
    if not insight_id or not action_id:
        raise HTTPException(status_code=400, detail=api_error("validation.invalid_payload"))
    allowed = {"try_7_days", "show_more_like_this", "show_fewer_low_response"}
    if action_id not in allowed:
        raise HTTPException(status_code=400, detail=api_error("validation.invalid_payload"))

    state = get_pattern_actions_state(db, user_id=current_user.id)
    prefs: dict = dict(state.get("preferences") or {})
    experiments: list = list(state.get("experiments") or [])

    now = datetime.now(UTC)
    until = now + timedelta(days=7)

    if action_id == "try_7_days":
        experiments = [e for e in experiments if str(e.get("insight_id") or "") != insight_id]
        experiments.append(
            {
                "insight_id": insight_id,
                "action_id": action_id,
                "started_at": now.isoformat(),
                "until": until.isoformat(),
            }
        )
    elif action_id == "show_more_like_this":
        prefs[f"more_like:{insight_id}"] = True
    elif action_id == "show_fewer_low_response":
        prefs["deprioritize_low_quality_profiles"] = True

    next_state = {"experiments": experiments[:24], "preferences": prefs}
    upsert_pattern_actions_state(db, user_id=current_user.id, state=next_state)
    track_event(
        db,
        "pattern_insight_action",
        user_id=current_user.id,
        payload={"insight_id": insight_id, "action_id": action_id},
    )
    return {"ok": True, "actions_state": next_state}


@router.post("/insights/feedback")
def ai_insights_feedback(
    payload: dict = Body(default={}),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    insight_id = str(payload.get("insight_id") or "").strip()
    helpful = payload.get("helpful")
    if not insight_id or not isinstance(helpful, bool):
        raise HTTPException(status_code=400, detail=api_error("validation.invalid_payload"))
    track_event(
        db,
        "pattern_insight_feedback",
        user_id=current_user.id,
        payload={"insight_id": insight_id, "helpful": helpful},
    )
    db.commit()
    return {"ok": True}


@router.post("/meeting-options", response_model=MeetingOptionsResponse)
async def meeting_options(
    req: MeetingOptionsRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    readiness = int(req.meeting_readiness)
    readiness = max(0, min(100, readiness))

    def _track_meeting_options_response(resp: dict) -> dict:
        mo = resp.get("meeting_options") if isinstance(resp, dict) else None
        if isinstance(mo, list) and len(mo) > 0:
            try:
                track_event(
                    db,
                    "meeting_suggested",
                    user_id=current_user.id,
                    payload={"source": "meeting_options", "readiness": readiness, "count": len(mo)},
                )
            except Exception:
                pass
        return resp

    if readiness < 60:
        return {"meeting_options": []}

    # Rate-limit as an AI feature (premium users have higher limits).
    try:
        enforce_ai_limits(db, current_user.id)
    except RateLimitExceeded:
        return _track_meeting_options_response(_meeting_options_fallback(readiness=readiness))

    if not settings.ENABLE_AI_SUGGESTIONS or settings.AI_PROVIDER != "gemini" or not (settings.GEMINI_API_KEY or "").strip():
        return _track_meeting_options_response(_meeting_options_fallback(readiness=readiness))

    from app.services.app_language import normalize_app_language

    locale = normalize_app_language(req.locale or "en")
    user_payload = {"messages": req.messages, "meeting_readiness": readiness, "locale": locale}

    system = (
        "You are NEYRA Copilot.\n"
        "Goal: Generate natural meeting suggestion.\n"
        "Rules:\n"
        "- If readiness < 60: DO NOT suggest meeting (return empty list).\n"
        "- If 60–80: soft suggestion.\n"
        "- If 80+: confident but light suggestion.\n"
        "- Style: natural, casual, safe (coffee, walk, public place).\n"
        "- DO NOT push aggressively.\n"
        "- DO NOT sound desperate.\n"
        "- DO NOT say anything like 'meet urgently'.\n"
        "- DO NOT be sexual.\n"
        "- ALWAYS keep an optional vibe (it's okay if they say no).\n"
        "Output STRICT JSON only:\n"
        '{ "meeting_options": ["..."] }\n'
        "Do not add extra keys."
    )

    async def _meeting_options_gemini() -> dict:
        client = GeminiClient()
        out = await client.generate_json(
            system_prompt=system,
            user_prompt=f"INPUT_JSON:\n{user_payload}",
            temperature=0.45 if readiness < 80 else 0.55,
            max_output_tokens=220,
            model=settings.GEMINI_CHAT_MODEL,
        )
        opts = out.get("meeting_options") if isinstance(out, dict) else None
        if not isinstance(opts, list):
            raise ValueError("invalid_meeting_options_shape")
        cleaned = [str(x or "").strip() for x in opts if str(x or "").strip()]
        if not cleaned:
            raise ValueError("empty_meeting_options")
        return {"meeting_options": cleaned[:3]}

    async def _meeting_options_fb() -> dict:
        set_last_provider_used("fallback")
        incr_fallback_24h()
        return _meeting_options_fallback(readiness=readiness)

    resp = await safe_ai_generate_async(
        _meeting_options_gemini,
        _meeting_options_fb,
        endpoint="meeting-options",
        locale=locale,
    )
    return _track_meeting_options_response(resp)


@router.post("/meeting-readiness", response_model=MeetingReadinessResponse)
async def meeting_readiness(
    req: MeetingReadinessRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from app.services.app_language import normalize_app_language
    from app.models.user_report import UserReport

    def _coerce_messages(raw) -> list[dict]:
        msgs_raw = raw if isinstance(raw, list) else []
        out: list[dict] = []
        for m in msgs_raw[-20:]:
            if isinstance(m, str):
                tx = str(m or "").strip()
                if tx:
                    out.append({"role": "them", "text": tx, "ts_ms": None})
                continue
            if not isinstance(m, dict):
                continue
            role = str(m.get("role") or "").strip().lower()
            role = "me" if role == "me" else "them" if role == "them" else "them"
            tx = str(m.get("text") or "").strip()
            if not tx:
                continue
            ts_ms = m.get("ts_ms")
            try:
                ts_ms = int(ts_ms) if ts_ms is not None else None
            except Exception:
                ts_ms = None
            out.append({"role": role, "text": tx, "ts_ms": ts_ms})
        return out

    msgs = _coerce_messages(req.messages)
    locale = normalize_app_language(req.locale or "en")

    partner_user_id = int(req.partner_user_id or 0) or (int(req.thread_id or 0) if req.thread_id else 0)
    partner_user_id = int(partner_user_id) if int(partner_user_id) > 0 else 0

    # Safety gates (require partner id).
    if partner_user_id > 0:
        # Blocked must short-circuit before match checks (match_partner.users_are_matched returns False on block).
        if is_blocked(db, int(current_user.id), int(partner_user_id)):
            return {
                "stage": "early",
                "score": 0,
                "reason": "Safety: blocked chat.",
                "suggested_action": "keep_chatting",
                "meeting_options": [],
                "meeting_readiness": 0,
                "reasoning": ["blocked"],
                "risk_level": "high",
                "confidence": 0,
                "suggest_action": "continue",
                "readiness_score": 0,
                "closer_stage": "opener",
                "closer_suggestions": [],
                "show_moment_hint": False,
            }
        if not users_are_matched(db, int(current_user.id), int(partner_user_id)):
            raise HTTPException(status_code=403, detail=api_error("chat.match_required"))
        open_report = (
            db.query(UserReport.id)
            .filter(
                UserReport.status == "open",
                or_(
                    and_(UserReport.reporter_id == int(current_user.id), UserReport.reported_user_id == int(partner_user_id)),
                    and_(UserReport.reporter_id == int(partner_user_id), UserReport.reported_user_id == int(current_user.id)),
                ),
            )
            .first()
            is not None
        )
        if open_report:
            return {
                "stage": "early",
                "score": 0,
                "reason": "Safety: report flags.",
                "suggested_action": "keep_chatting",
                "meeting_options": [],
                "meeting_readiness": 0,
                "reasoning": ["report flags"],
                "risk_level": "high",
                "confidence": 0,
                "suggest_action": "continue",
                "readiness_score": 0,
                "closer_stage": "opener",
                "closer_suggestions": [],
                "show_moment_hint": False,
            }

    total = len(msgs)
    me_cnt = sum(1 for m in msgs if m.get("role") == "me")
    them_cnt = sum(1 for m in msgs if m.get("role") == "them")
    me_q = sum(1 for m in msgs if m.get("role") == "me" and "?" in str(m.get("text") or ""))
    them_q = sum(1 for m in msgs if m.get("role") == "them" and "?" in str(m.get("text") or ""))
    lengths = [len(str(m.get("text") or "").strip()) for m in msgs if str(m.get("text") or "").strip()]
    avg_len = float(sum(lengths) / max(1, len(lengths))) if lengths else 0.0
    one_wordish = sum(1 for m in msgs if len(str(m.get("text") or "").strip().split()) <= 2)
    cold_ratio = float(one_wordish) / float(max(1, total))

    last_ts_ms = None
    for m in reversed(msgs):
        if isinstance(m.get("ts_ms"), int):
            last_ts_ms = int(m.get("ts_ms"))
            break
    stalled = False
    if last_ts_ms is not None:
        try:
            age_ms = int(datetime.now(UTC).timestamp() * 1000) - int(last_ts_ms)
            stalled = age_ms >= 12 * 60 * 60 * 1000
        except Exception:
            stalled = False

    my_profile = db.query(Profile).filter(Profile.user_id == int(current_user.id)).first()
    partner_profile = db.query(Profile).filter(Profile.user_id == int(partner_user_id)).first() if partner_user_id > 0 else None
    my_age = _age_from_profile(my_profile)
    partner_age = _age_from_profile(partner_profile)
    if (my_age is not None and my_age < 18) or (partner_age is not None and partner_age < 18):
        return {
            "stage": "early",
            "score": 0,
            "reason": "Safety: under 18.",
            "suggested_action": "keep_chatting",
            "meeting_options": [],
            "meeting_readiness": 0,
            "reasoning": ["under 18"],
            "risk_level": "high",
            "confidence": 0,
            "suggest_action": "continue",
            "readiness_score": 0,
            "closer_stage": "opener",
            "closer_suggestions": [],
            "show_moment_hint": False,
        }

    my_city = (str(getattr(my_profile, "city", "") or "").strip() if my_profile else "") or str(req.city or "").strip()
    partner_city = (str(getattr(partner_profile, "city", "") or "").strip() if partner_profile else "")
    same_city = bool(my_city and partner_city and my_city.lower() == partner_city.lower())

    shared_interest = False
    try:
        from app.domain.matching.utils import normalize_tokens, split_csv

        mine = normalize_tokens(split_csv(getattr(my_profile, "interests", "") or "")) if my_profile else set()
        theirs = normalize_tokens(split_csv(getattr(partner_profile, "interests", "") or "")) if partner_profile else set()
        shared_interest = bool(mine and theirs and len(set(mine) & set(theirs)) > 0)
    except Exception:
        shared_interest = False

    tone = _positive_tone_score([str(m.get("text") or "") for m in msgs[-10:]])

    if stalled and total >= 6:
        stage = "stalled"
        suggested_action = "revive"
    elif total < 6:
        stage = "early"
        suggested_action = "keep_chatting"
    elif total < 15:
        stage = "warming"
        suggested_action = "ask_deeper"
    else:
        stage = "ready"
        suggested_action = "suggest_meeting"

    balance = 1.0 - abs(me_cnt - them_cnt) / float(max(1, me_cnt + them_cnt))
    question_score = min(1.0, (me_q + them_q) / 6.0)
    depth = min(1.0, avg_len / 90.0)
    engage = 1.0 - min(1.0, cold_ratio)
    profile_signal = 1.0 if (same_city or shared_interest) else 0.0
    score_f = 0.30 * balance + 0.22 * question_score + 0.22 * depth + 0.16 * tone + 0.10 * engage + 0.08 * profile_signal
    raw_score = int(max(0, min(100, round(40 + score_f * 60))))

    if stage == "early":
        score = min(raw_score, 55)
    elif stage == "warming":
        score = min(raw_score, 74)
    elif stage == "stalled":
        score = min(raw_score, 45)
    else:
        score = raw_score

    has_min_exchange = me_cnt >= 3 and them_cnt >= 3 and total >= 15
    engaged_both = me_q >= 1 and them_q >= 1 and avg_len >= 8 and tone >= 0.35 and cold_ratio <= 0.55

    plan_tier = "free"
    try:
        plan = SubscriptionService().get_active_plan(db, int(current_user.id))
        plan_tier = plan if plan in {"free", "premium", "premium_plus"} else "free"
    except Exception:
        plan_tier = "free"
    free_meeting_used = False
    if plan_tier == "free":
        st = _daily_boosts_get(db, user_id=int(current_user.id))
        free_meeting_used = bool(st.get("meeting_used"))

    cooldown_ok = True
    if partner_user_id > 0:
        cooldown_ok = _meeting_prompt_cooldown_ok(int(current_user.id), int(partner_user_id), cooldown_days=7)

    meeting_options: list[dict] = []
    if stage == "ready" and score >= 75 and has_min_exchange and engaged_both and cooldown_ok and not free_meeting_used:
        meeting_options = _meeting_templates(locale, city=my_city if plan_tier != "free" else None)

    if stage == "ready" and not meeting_options:
        suggested_action = "ask_deeper" if not stalled else "revive"

    reason_parts = []
    if stage == "early":
        reason_parts.append("Conversation is still new.")
    elif stage == "warming":
        reason_parts.append("Good momentum — deepen the vibe.")
    elif stage == "stalled":
        reason_parts.append("It’s been quiet for a while.")
    else:
        reason_parts.append("Strong back-and-forth and good tone.")
    if same_city:
        reason_parts.append("Same city.")
    if shared_interest:
        reason_parts.append("Shared interests.")
    if free_meeting_used:
        reason_parts.append("Free daily meeting suggestion already used.")
    if not cooldown_ok:
        reason_parts.append("Meeting prompt cooldown active.")
    reason = " ".join(reason_parts).strip()

    if bool(getattr(req, "mark_shown", False)) and partner_user_id > 0 and meeting_options:
        _mark_meeting_prompt_shown(int(current_user.id), int(partner_user_id))
        if plan_tier == "free":
            _daily_boosts_consume(db, user_id=int(current_user.id), boost_type="meeting")

    risk_level = "low" if stage == "ready" and score >= 75 else "high" if stage in {"stalled", "early"} else "medium"
    confidence = max(0, min(100, int(score)))
    suggest_action = "suggest_meeting" if stage == "ready" else "escalate" if stage == "warming" else "continue"
    reasoning = [
        "balanced" if balance >= 0.55 else "one-sided",
        "questions" if (me_q + them_q) >= 2 else "low questions",
        "positive tone" if tone >= 0.35 else "neutral tone",
    ]

    _store_meeting_stage(
        db,
        int(current_user.id),
        int(partner_user_id) if partner_user_id > 0 else None,
        stage,
        confidence,
        suggest_action,
    )

    _stalled_for_closer = bool(stage == "stalled")
    closer_stage, _ = compute_closer_stage(msgs, stalled_chat=_stalled_for_closer)
    closer_city = my_city if plan_tier != "free" else None
    closer_suggestions = closer_meeting_suggestions_three(locale, closer_stage, city=closer_city)
    show_moment_hint = closer_show_moment_hint(
        score=int(score),
        closer_stage=closer_stage,
        stage_mr=str(stage),
        total_messages=int(total),
    )

    out_mr = {
        "stage": stage,
        "score": int(score),
        "reason": reason,
        "suggested_action": suggested_action,
        "meeting_options": meeting_options,
        # legacy:
        "meeting_readiness": int(score),
        "reasoning": [r for r in reasoning if r][:8],
        "risk_level": risk_level,
        "confidence": confidence,
        "suggest_action": suggest_action,
        "readiness_score": int(score),
        "closer_stage": closer_stage,
        "closer_suggestions": closer_suggestions[:3],
        "show_moment_hint": bool(show_moment_hint),
    }
    if show_moment_hint and closer_suggestions and not meeting_options:
        try:
            track_event(
                db,
                "meeting_suggested",
                user_id=current_user.id,
                payload={
                    "partner_user_id": int(partner_user_id) if partner_user_id > 0 else None,
                    "stage": stage,
                    "score": int(score),
                    "closer_stage": closer_stage,
                    "variant": "moment_hint",
                    "source": "meeting_readiness",
                },
            )
        except Exception:
            pass
    if meeting_options:
        try:
            track_event(
                db,
                "meeting_suggested",
                user_id=current_user.id,
                payload={
                    "partner_user_id": int(partner_user_id) if partner_user_id > 0 else None,
                    "stage": stage,
                    "score": int(score),
                    "options_count": len(meeting_options),
                    "source": "meeting_readiness",
                },
            )
        except Exception:
            pass
    return out_mr


@router.post("/meeting-ready", response_model=MeetingReadyResponse)
async def meeting_ready(
    req: MeetingReadinessRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Focused meeting momentum payload (readiness score + three closer lines)."""
    payload = await meeting_readiness(req, current_user, db)
    if not isinstance(payload, dict):
        payload = {}
    sc = int(payload.get("score") if payload.get("score") is not None else payload.get("readiness_score") or 0)
    sc = max(0, min(100, sc))
    return MeetingReadyResponse(
        readiness_score=sc,
        closer_stage=str(payload.get("closer_stage") or "early_chat"),
        suggestions=[str(x or "").strip() for x in (payload.get("closer_suggestions") or []) if str(x or "").strip()][:3],
        show_moment_hint=bool(payload.get("show_moment_hint")),
    )


@router.post("/learning/event")
def ai_learning_event(
    payload: dict = Body(default={}),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Store behavior-only AI interaction signals. Never stores raw text."""
    name = str(payload.get("name") or "").strip()
    if name not in {"ai_options_shown", "ai_option_selected", "ai_option_sent"}:
        raise HTTPException(status_code=400, detail="Invalid event name")

    style = str(payload.get("style") or "").strip().lower()
    if style not in {"light", "flirty", "deep", ""}:
        style = ""
    index = payload.get("index")
    try:
        index_val = int(index) if index is not None else None
    except Exception:
        index_val = None
    edited = bool(payload.get("edited")) if name == "ai_option_sent" else None

    final_text = str(payload.get("final_text") or "") if name == "ai_option_sent" else ""
    # Derive stats and discard content.
    length = len(final_text.strip()) if final_text else None
    emoji_level = _emoji_level(final_text) if final_text else None
    final_text = ""  # ensure not kept accidentally

    row = db.query(UserAiProfile).filter(UserAiProfile.user_id == current_user.id).first()
    if not row:
        row = UserAiProfile(user_id=current_user.id)
    # Update aggregates only on send (strong signal).
    if name == "ai_option_sent":
        samples = int(getattr(row, "samples", 0) or 0)
        alpha = 0.18 if samples < 10 else 0.10
        if length is not None:
            row.avg_message_length = _ewma(float(getattr(row, "avg_message_length", 0.0) or 0.0), float(length), alpha)
        if emoji_level is not None:
            row.emoji_usage_level = _ewma(float(getattr(row, "emoji_usage_level", 0.0) or 0.0), float(emoji_level), alpha)
        if edited is not None:
            row.edit_rate = _ewma(float(getattr(row, "edit_rate", 0.0) or 0.0), 1.0 if edited else 0.0, alpha)
        row.samples = samples + 1
        if style in {"light", "flirty", "deep"}:
            # simple preference: last-sent style wins with a small inertia.
            row.preferred_style = style
    elif name == "ai_option_selected":
        # Light touch: selection influences preferred style, but less than send.
        if style in {"light", "flirty", "deep"} and not bool(payload.get("edited")):
            row.preferred_style = style

    row.updated_at = datetime.now(UTC)
    db.add(row)
    db.commit()

    track_event(
        db,
        "ai_learning_event",
        user_id=current_user.id,
        payload={"name": name, "style": style or None, "index": index_val, "edited": edited, "length": length, "emoji_level": emoji_level},
    )
    return {"ok": True}

def _norm_for_sim(s: str) -> str:
    return " ".join((s or "").strip().lower().replace("’", "'").split())

def _has_english(text: str) -> bool:
    # Strict: no ASCII latin letters allowed.
    import re

    return bool(re.search(r"[A-Za-z]", text or ""))


_GENERIC_PHRASES = {
    "що ти думаєш",
    "що ти про це думаєш",
    "що маєш на увазі",
    "що ти маєш на увазі",
    "розкажи більше",
    "розкажеш трохи більше",
    "розкажеш більше",
}


_UK_REPLY_SOFT_BANS = (
    "що ти думаєш",
    "що ти про це думаєш",
    "що маєш на увазі",
    "що ти маєш на увазі",
)


def _has_banned_uk_reply_phrase(text: str) -> bool:
    low = _norm_for_sim(text)
    return any(p in low for p in _UK_REPLY_SOFT_BANS)


def _scrub_banned_uk_reply_phrases(text: str) -> str:
    """Remove shallow Ukrainian filler banned for dating UX (last-resort rewrite)."""
    import re

    t = text or ""
    subs: list[tuple[re.Pattern[str], str]] = [
        (re.compile(r"що\s+ти\s+про\s+це\s+думаєш", re.IGNORECASE), "що саме тебе зачепило"),
        (re.compile(r"що\s+ти\s+думаєш", re.IGNORECASE), "як ти це відчуваєш"),
        (re.compile(r"що\s*(ти\s*)?маєш\s+на\s+увазі", re.IGNORECASE), "про який саме момент"),
    ]
    for rx, rep in subs:
        t = rx.sub(rep, t)
    return _ensure_question_short(t.strip())


def _same_question(a: str, b: str) -> bool:
    """
    Detect "same question reworded" cheaply:
    - normalize
    - strip punctuation
    - compare similarity
    - also catch generic forbidden questions
    """
    import re

    aa = _norm_for_sim(a)
    bb = _norm_for_sim(b)
    aa = re.sub(r"[^0-9a-zа-яіїєґ' ]+", " ", aa)
    bb = re.sub(r"[^0-9a-zа-яіїєґ' ]+", " ", bb)
    aa = " ".join(aa.split())
    bb = " ".join(bb.split())
    if not aa or not bb:
        return False
    if any(p in aa for p in _GENERIC_PHRASES) or any(p in bb for p in _GENERIC_PHRASES):
        return True
    # If questions are very close, treat as same.
    return _pair_similarity(aa, bb) > 0.72


def _overlap_ratio(user_text: str, option_text: str) -> float:
    """
    Rough overlap ratio of content words (0..1) = |intersect| / |user_words|.
    Used to prevent repeating the user's message.
    """
    import re

    def toks(s: str) -> set[str]:
        s = (s or "").lower()
        s = re.sub(r"[^0-9a-zа-яіїєґ' ]+", " ", s)
        parts = [p.strip() for p in s.split() if p.strip()]
        # drop very short tokens
        parts = [p for p in parts if len(p) >= 3]
        # small stoplist to reduce false positives
        stop = {"що", "це", "там", "тут", "про", "яка", "який", "які", "ти", "ви", "мене", "тебе", "тобі", "мені", "вона", "він", "вони", "і", "але", "бо"}
        return {p for p in parts if p not in stop}

    u = toks(user_text)
    if not u:
        return 0.0
    o = toks(option_text)
    if not o:
        return 0.0
    inter = len(u.intersection(o))
    return float(inter) / float(max(1, len(u)))


def _keyword_set(text: str, *, max_n: int = 8) -> set[str]:
    import re

    s = (text or "").lower()
    s = re.sub(r"[^0-9a-zа-яіїєґ' ]+", " ", s)
    parts = [p.strip() for p in s.split() if p.strip()]
    parts = [p for p in parts if len(p) >= 4]
    # keep first unique words as "keywords" proxy
    out: list[str] = []
    for p in parts:
        if p not in out:
            out.append(p)
        if len(out) >= max_n:
            break
    return set(out)


def _keyword_jaccard(a: str, b: str) -> float:
    aa = _keyword_set(a)
    bb = _keyword_set(b)
    if not aa or not bb:
        return 0.0
    inter = len(aa.intersection(bb))
    uni = len(aa.union(bb))
    return float(inter) / float(max(1, uni))


def _structure_sig(text: str) -> str:
    """
    Cheap structure signature: first interrogative word + first 6 tokens (normalized).
    """
    import re

    s = _norm_for_sim(text)
    s = re.sub(r"[^0-9a-zа-яіїєґ' ]+", " ", s)
    toks = [t for t in s.split() if t]
    if not toks:
        return ""
    wh = ""
    for w in toks[:6]:
        if w in {"що", "чому", "як", "де", "коли", "навіщо", "яка", "який", "які", "кого"}:
            wh = w
            break
    head = " ".join(toks[:6])
    return f"{wh}|{head}"

def _extract_place_hint(text: str) -> str | None:
    t = (text or "").strip()
    low = t.lower()
    if "верховин" in low:
        return "Верховині"
    if "київ" in low:
        return "Києві"
    if "львів" in low:
        return "Львові"
    if "одес" in low:
        return "Одесі"
    return None


def _fallback_3_replies_en(last_message: str, *, continue_mode: bool) -> list[str]:
    msg = " ".join((last_message or "").strip().split())
    low = msg.lower()
    place = _extract_place_hint(last_message)
    where_en = f" near {place}" if place else ""

    if continue_mode:
        light = _ensure_question_short(
            f"Haha I’m into that 🙂 I’d probably nerd out on the little details—would you rather unpack the story first or the vibe{where_en}?"
        )
        flirty = _ensure_question_short(
            "That lands for me 🙂 I’m torn between cozy chat or doing something tiny together—what sounds lighter tonight?"
        )
        deep = _ensure_question_short(
            "I hear you 🙂 for you is it more about headspace or the people around you when you talk like that?"
        )
        if ("places" in low or "місця" in low or "места" in low) and ("people" in low or "люди" in low or "людьми" in low):
            light = _ensure_question_short(
                "That mix sounds real 🙂 would you rather spend a day soaking up landscape or people-watching there?"
            )
            flirty = _ensure_question_short(
                "Okay I’m hooked 🙂 secret viewpoint hike or slow café afternoon—what’s more your speed?"
            )
            deep = _ensure_question_short(
                "I get why that sticks 🙂 mountains-quiet or human-warm—what pulls you harder right now?"
            )
    else:
        light = _ensure_question_short(
            f"Interesting 🙂 I’d answer with something low-pressure—want to lead with the facts or how it felt{where_en}?"
        )
        flirty = _ensure_question_short(
            "Okay 🙂 tiny choices—voice-note ramble or tight text when you tell me more?"
        )
        deep = _ensure_question_short(
            "Makes sense 🙂 are you usually more ‘plan the week’ or ‘see what happens’ when stuff like this comes up?"
        )
    return [light, flirty, deep]


def _fallback_3_replies_uk(last_message: str, *, continue_mode: bool) -> list[str]:
    """Deterministic Ukrainian fallback when UI locale is uk (shared with chat-brain / wingman)."""
    from app.services.ai.conversation.contextual_fallback_triples import uk_reply_fallback_three_lines

    return uk_reply_fallback_three_lines(last_message or "", continue_mode=continue_mode)


async def _fallback_3_replies_localized(
    last_message: str,
    *,
    locale: str | None,
    continue_mode: bool,
    closer_stage: str | None = None,
) -> list[str]:
    import logging

    from app.services.ai.ai_fallback_engine import sanitize_fallback_lines_for_locale
    from app.services.ai.locale_rewrite import batch_translate_lines

    log = logging.getLogger("neyra.ai.fallback")
    loc = normalize_ai_request_locale(locale)

    if (closer_stage or "").strip():
        from app.services.ai.conversation.closer_meeting import closer_copilot_fallback_lines

        base = closer_copilot_fallback_lines(loc, str(closer_stage), str(last_message or ""), continue_mode)
        if loc == "uk":
            log.info(
                "fallback_locale_used",
                extra={"event": "fallback_locale_used", "locale": "uk", "source": "reply_localized_closer"},
            )
        return sanitize_fallback_lines_for_locale(base, loc, context="reply_3_closer")

    if loc == "uk":
        base = _fallback_3_replies_uk(last_message, continue_mode=continue_mode)
        log.info(
            "fallback_locale_used",
            extra={"event": "fallback_locale_used", "locale": "uk", "source": "reply_localized_open"},
        )
        return sanitize_fallback_lines_for_locale(base, "uk", context="reply_3_open")

    if loc == "en":
        return _fallback_3_replies_en(last_message, continue_mode=continue_mode)

    from app.services.ai.ai_fallback_phrases import timed_now_emergency_triple

    a, b, c = timed_now_emergency_triple(loc)
    phrase_bank = [_ensure_question_short(a), _ensure_question_short(b), _ensure_question_short(c)]
    try:
        en_based = _fallback_3_replies_en(last_message, continue_mode=continue_mode)
        tr = await batch_translate_lines(en_based, loc)
        if len(tr) == len(en_based) and all((x or "").strip() for x in tr):
            return sanitize_fallback_lines_for_locale(
                [_ensure_question_short(x) for x in tr],
                loc,
                context="reply_3_open_translated",
            )
    except Exception:
        pass
    return sanitize_fallback_lines_for_locale(phrase_bank, loc, context="reply_3_open_phrase_bank")


def _copilot_fallback_labels(loc: str) -> tuple[str, str, str]:
    from app.services.ai.ai_fallback_engine import copilot_fallback_labels

    return copilot_fallback_labels(loc)


def _recent_question_texts(chat: list[dict], *, limit: int = 6) -> list[str]:
    out: list[str] = []
    for m in reversed(chat or []):
        t = str(m.get("text") or "").strip()
        if not t:
            continue
        if "?" in t:
            out.append(t)
        if len(out) >= limit:
            break
    return out


def _best_index_for_stage(stage: str | None, mutuality_score: int | None) -> int:
    st = (stage or "").strip().lower()
    m = int(mutuality_score or 0)
    # Conservative: if mutuality is low, prefer LIGHT.
    if m < 45:
        return 0
    if st == "ready":
        return 2
    if st == "engaged":
        return 1
    # cold/warming/unknown
    return 0


def _pair_similarity(a: str, b: str) -> float:
    # Fast lexical similarity (no heavy deps). 0..1
    import difflib

    aa = _norm_for_sim(a)
    bb = _norm_for_sim(b)
    if not aa or not bb:
        return 0.0
    return float(difflib.SequenceMatcher(a=aa, b=bb).ratio())


def _diversity_score(texts: list[str]) -> float:
    if not texts or len(texts) < 2:
        return 1.0
    sims = []
    for i in range(len(texts)):
        for j in range(i + 1, len(texts)):
            sims.append(_pair_similarity(texts[i], texts[j]))
    if not sims:
        return 1.0
    # diversity = 1 - max similarity
    return max(0.0, min(1.0, 1.0 - max(sims)))


def _ensure_question_short(text: str) -> str:
    s = " ".join((text or "").strip().split())
    if not s:
        return "Супер 🙂 про що саме в цьому тебе найбільше зачепило?"
    if not s.endswith("?"):
        s = s.rstrip(".!… ")
        s = f"{s}?"
    # 1–2 sentences max
    parts = [p.strip() for p in s.split("?") if p.strip()]
    if len(parts) > 2:
        s = "? ".join(parts[:2]).strip() + "?"
    return s[:320]


def _avoid_generic_hi(text: str, locale: str | None) -> str:
    """
    Prevent dead/generic openers like "Hi" / "Hey" without substance.
    Keep it light but always add a hook + question.
    """
    t = " ".join((text or "").strip().split())
    low = t.lower().strip("!?. ")
    # Too short or pure greeting
    greetings_en = {"hi", "hey", "hello", "yo", "hiya"}
    greetings_ru = {"привет", "здравствуй", "здравствуйте", "хай"}
    greetings_uk = {"привіт", "вітаю", "доброго", "добрий", "хай"}
    if len(low) <= 6 and (low in greetings_en or low in greetings_ru or low in greetings_uk):
        loc = normalize_ai_request_locale(locale)
        if loc == "ru":
            return "Я поймал(а) твой вайб 🙂 что тебя больше всего радует в последнее время?"
        if loc == "uk":
            return "Я зловив(ла) твій вайб 🙂 що тебе останнім часом реально тішить?"
        if loc == "zh-TW":
            return "感受到你的風格了 🙂 這週最讓你開心的是什麼？"
        if loc == "zh":
            return "感受到你的风格了 🙂 这周最让你开心的是什么？"
        return "I caught your vibe 🙂 what’s been the best part of your week so far?"
    # If it starts with greeting and nothing else, nudge to add hook
    if low.startswith("hi") or low.startswith("hey") or low.startswith("hello"):
        if len(low) < 16 and ("?" not in t):
            return t + " 🙂 what made you join NEYRA?"
    return t


# Compatibility alias (tests + fallback generators expect this name).
def _ensure_question_ua(text: str) -> str:
    return _ensure_question_short(text)


def _manual_tweak(text: str, *, style: str) -> str:
    # Last-resort differentiation tweaks (keeps meaning but shifts tone/structure).
    t = _ensure_question_short(text)
    if style == "light":
        if "🙂" not in t:
            t = t.replace("?", " 🙂?")
        if t.lower().startswith("цікаво"):
            t = t.replace("Цікаво", "Слухай")
        return t
    if style == "flirty":
        if "🙂" not in t and "😉" not in t:
            t = t.replace("?", " 😉?")
        # Slightly more emotional but safe
        if "мені" not in t.lower():
            t = "Мені це реально зайшло. " + t[0].lower() + t[1:]
        return _ensure_question_short(t)
    # deep
    if "чому" not in t.lower() and "що саме" not in t.lower():
        t = t.replace("?", " — що саме в цьому для тебе найважливіше?")
        if not t.endswith("?"):
            t = t.rstrip(".!… ") + "?"
    return _ensure_question_short(t)

logger = logging.getLogger("neyra.ai.assist")

_AI_PROVIDER_TIMEOUT_S = 8.0

def _raise_gemini_failed(exc: Exception | None = None, *, endpoint: str | None = None) -> None:
    logger.error(
        "ai_request_failed",
        extra={
            "event": "ai_request_failed",
            "endpoint": endpoint,
            "error": (str(exc) if exc else "")[:800],
            "type": (type(exc).__name__ if exc else None),
            "ai_provider": "gemini",
        },
    )
    # Quota/rate-limit should be explicit so UI can show "limit reached" and avoid fake replies.
    if isinstance(exc, GeminiError) and str(getattr(exc, "code", "") or "") in {"quota_exhausted"}:
        detail = {
            "error": "ai_quota_exhausted",
            "message": "Today's AI limit has been reached. Please try again later.",
        }
        raise HTTPException(status_code=429, detail=detail)
    detail = {"error": "gemini_failed", "details": (str(exc) if exc else "")[:800]}
    raise HTTPException(status_code=503, detail=detail)


async def _with_timeout(coro, *, timeout_s: float = _AI_PROVIDER_TIMEOUT_S):
    return await asyncio.wait_for(coro, timeout=timeout_s)


def _resolve_ai_locale_for_request(
    *,
    req_locale: str | None,
    ai_locale: str | None,
    request: Request | None,
    db: Session,
    current_user: User,
    latest_user_message: str | None = None,
    prefer_message_locale: bool = False,
    route_label: str = "ai",
) -> str:
    profile_locale = ""
    try:
        me_profile = db.query(Profile).filter(Profile.user_id == int(current_user.id)).first()
        profile_locale = str(getattr(me_profile, "preferred_language", "") or "").strip()
    except Exception:
        profile_locale = ""
    transport_locale = ""
    try:
        if request is not None:
            transport_locale = str(
                request.headers.get("X-Neyra-Locale")
                or request.headers.get("X-Locale")
                or request.headers.get("X-UI-Locale")
                or request.query_params.get("locale")
                or ""
            ).strip()
    except Exception:
        transport_locale = ""
    accept_hdr = ""
    try:
        if request is not None:
            accept_hdr = str(request.headers.get("accept-language") or "")
    except Exception:
        accept_hdr = ""

    requested_ai_locale = str(ai_locale or "").strip().lower()
    if requested_ai_locale and requested_ai_locale != "auto":
        forced = normalize_chat_ai_locale(requested_ai_locale)
        log_ai_locale_resolved(
            route=route_label,
            resolved_locale=forced,
            resolution_source="ai_locale_override",
            req_locale_raw=str(req_locale or "").strip() or None,
            profile_locale_raw=profile_locale or None,
            accept_language=accept_hdr or None,
            transport_locale=transport_locale or None,
            ai_locale_override=str(ai_locale or "").strip() or None,
            prefer_message_locale=prefer_message_locale,
        )
        return forced

    chain_loc, chain_src = resolve_ai_locale_strict_chain(
        req_locale=req_locale,
        profile_locale=profile_locale or None,
        accept_language_header=accept_hdr or None,
        transport_locale=transport_locale or None,
    )

    if prefer_message_locale:
        # Explicit JSON locale always wins over partner-message sniffing (short English pings must not collapse UI locale).
        explicit_ui = str(req_locale or "").strip()
        if explicit_ui and explicit_ui.lower() not in {"auto"}:
            log_ai_locale_resolved(
                route=route_label,
                resolved_locale=chain_loc,
                resolution_source="request_body",
                req_locale_raw=str(req_locale or "").strip() or None,
                profile_locale_raw=profile_locale or None,
                accept_language=accept_hdr or None,
                transport_locale=transport_locale or None,
                ai_locale_override=None,
                prefer_message_locale=True,
            )
            return chain_loc

        decided_locale, source = resolve_ai_locale_decision(
            latest_user_message=latest_user_message,
            interface_locale=chain_loc if chain_loc != "en" else None,
            profile_locale=None,
        )
        msg_detect = None
        try:
            from app.services.ai.locale_decision import detect_message_locale

            msg_detect = detect_message_locale(latest_user_message)
        except Exception:
            msg_detect = None
        if decided_locale == "en" and source == "fallback":
            acc = locale_from_accept_language_header(accept_hdr)
            if acc:
                decided_locale = normalize_chat_ai_locale(acc)
                source = "accept_language"
        log_ai_locale_resolved(
            route=route_label,
            resolved_locale=decided_locale,
            resolution_source=f"message:{source}",
            req_locale_raw=str(req_locale or "").strip() or None,
            profile_locale_raw=profile_locale or None,
            accept_language=accept_hdr or None,
            transport_locale=transport_locale or None,
            ai_locale_override=None,
            prefer_message_locale=True,
            message_locale_detected=msg_detect,
        )
        return decided_locale

    log_ai_locale_resolved(
        route=route_label,
        resolved_locale=chain_loc,
        resolution_source=chain_src,
        req_locale_raw=str(req_locale or "").strip() or None,
        profile_locale_raw=profile_locale or None,
        accept_language=accept_hdr or None,
        transport_locale=transport_locale or None,
        ai_locale_override=None,
        prefer_message_locale=False,
    )
    return chain_loc


async def _enforce_ai_texts_locale_once(
    texts: list[str],
    *,
    locale: str,
) -> list[str]:
    from app.services.ai.output_script_locale import text_matches_requested_locale
    from app.services.ai.locale_rewrite import enforce_text_locale

    cleaned = [str(t or "").strip() for t in (texts or [])]
    if not cleaned:
        return cleaned
    if all(text_matches_requested_locale(t, locale) for t in cleaned if t):
        return cleaned
    # Auto-retry once with stronger instruction.
    try:
        client = GeminiClient()
        payload = {"language": locale, "texts": cleaned}
        out = await client.generate_json(
            system_prompt=(
                "You are a strict language normalizer.\n"
                "IMPORTANT: Answer ONLY in the requested language.\n"
                "Rewrite each input line in the same meaning/tone but in requested language.\n"
                'Return strict JSON: {"texts":["..."]}.'
            ),
            user_prompt=f"INPUT_JSON:\n{payload}",
            temperature=0.1,
            max_output_tokens=420,
        )
        rows = out.get("texts") if isinstance(out, dict) else None
        if isinstance(rows, list):
            rewritten = [str(x or "").strip() for x in rows][: len(cleaned)]
            if len(rewritten) == len(cleaned) and all(text_matches_requested_locale(t, locale) for t in rewritten if t):
                return rewritten
    except Exception:
        pass
    # Last-resort per-line locale enforcement.
    out_lines: list[str] = []
    for t in cleaned:
        try:
            fixed = await enforce_text_locale(t, locale)
        except Exception:
            fixed = t
        out_lines.append(str(fixed or "").strip())
    return out_lines


def _reply_question_tone(*, text: str, tone: str | None) -> dict[str, str]:
    s = " ".join(str(text or "").strip().split())
    if not s:
        return {"reply": "", "question": "", "tone": str(tone or "playful")}
    q = ""
    reply = s
    if "?" in s:
        idx = s.rfind("?")
        head = s[: idx + 1].strip()
        # split into pre-question + question when possible
        q_start = max(head.rfind(". "), head.rfind("! "), head.rfind("… "), head.rfind("? "))
        if q_start >= 0 and q_start + 2 < len(head):
            reply = head[: q_start + 1].strip()
            q = head[q_start + 1 :].strip()
        else:
            q = head if head.endswith("?") else f"{head}?"
            reply = ""
    if not q:
        q = s if s.endswith("?") else f"{s.rstrip('.!… ')}?"
    if not reply:
        reply = s[: max(0, len(s) - len(q))].strip()
    return {"reply": reply[:320], "question": q[:240], "tone": str(tone or "playful")}


def _attach_structured_to_timed_options(options: list[dict]) -> list[dict]:
    out: list[dict] = []
    for row in options or []:
        if not isinstance(row, dict):
            continue
        txt = str(row.get("text") or "").strip()
        tone = str(row.get("style") or "playful").strip().lower() or "playful"
        rq = _reply_question_tone(text=txt, tone=tone)
        out.append({**row, "reply": rq["reply"], "question": rq["question"], "tone": rq["tone"]})
    return out


def _attach_structured_to_copilot_options(options: list[dict]) -> list[dict]:
    out: list[dict] = []
    for row in options or []:
        if not isinstance(row, dict):
            continue
        txt = str(row.get("text") or "").strip()
        tone = str(row.get("style") or "playful").strip().lower() or "playful"
        rq = _reply_question_tone(text=txt, tone=tone)
        out.append({**row, "reply": rq["reply"], "question": rq["question"], "tone": rq["tone"]})
    return out


def _log_ai_fallback(endpoint: str, *, reason: str, locale: str, exc: BaseException | None = None) -> None:
    emitted = log_ai_fallback_triggered(
        endpoint=endpoint,
        locale=locale,
        reason=reason,
        error_message=str(exc) if exc is not None else reason,
        provider="gemini",
    )
    if not emitted:
        return
    try:
        log_ai_provider_final(ai_provider_final="fallback", endpoint=endpoint, reason=reason)
    except Exception:
        pass


def _raise_ai_limit_paywall() -> None:
    raise HTTPException(
        status_code=402,
        detail={
            "error": "limit_reached",
            "message": "Upgrade to continue using AI",
            "plan_required": "premium",
        },
    )


def _raise_ai_limit_hit() -> None:
    """Unified paywall signal for daily AI caps (free/premium tiers)."""
    raise HTTPException(
        status_code=402,
        detail={
            "error": "ai_limit_hit",
            "message": "Daily AI limit reached — upgrade for more.",
            "upgrade_hint": "unlock_unlimited_ai",
        },
    )


def _raise_ai_unlock_after_match() -> None:
    raise HTTPException(
        status_code=402,
        detail={
            "error": "ai_unlock_after_first_match",
            "message": "AI unlocks after your first match",
        },
    )


@router.get("/status")
def ai_status():
    provider = (settings.AI_PROVIDER or "mock").strip().lower()
    enabled = bool(settings.ENABLE_AI_SUGGESTIONS)
    has_key = bool((settings.GEMINI_API_KEY or "").strip()) if provider == "gemini" else bool((settings.OPENAI_API_KEY or "").strip()) if provider == "openai" else False
    model = (settings.GEMINI_MODEL or "").strip() if provider == "gemini" else (settings.AI_MODEL or "").strip()
    return {
        "enabled": enabled,
        "provider": provider,
        "model": model or None,
        "has_api_key": has_key,
    }

_OPENER_STYLE_ALIASES = {
    "fun": "playful",
    "light": "playful",
    "playful": "playful",
    "confident": "confident",
    "direct": "confident",
    "curious": "curious",
    "thoughtful": "curious",
    # Premium Plus styles (pass-through)
    "flirty": "flirty",
    "witty": "witty",
    "charming": "charming",
    "direct": "direct",
    "thoughtful_plus": "thoughtful",
    "tease_lightly": "tease_lightly",
    "tease lightly": "tease_lightly",
    "tease-lightly": "tease_lightly",
}

_PLUS_OPENER_STYLES = {"flirty", "witty", "charming", "direct", "thoughtful", "tease_lightly"}

# Premium (and premium_plus): richer rewrite tones. Free users are clamped to FREE_REWRITE_MODES.
_PREMIUM_REWRITE_MODES = {
    "flirty",
    "witty",
    "charming",
    "direct",
    "thoughtful",
    "tease_lightly",
    "confident",
    "softer",
    "romantic",
    "deep",
    "playful",
}
_FREE_REWRITE_MODES = {"polish", "more_natural", "shorter"}


def _normalize_improve_reply_mode(raw: str | None) -> str:
    m = " ".join((raw or "polish").strip().lower().split())
    if not m:
        m = "polish"
    m = m.replace("-", "_")
    aliases = {
        "natural": "more_natural",
        "flirtier": "flirty",
        "more_flirty": "flirty",
        "funnier": "witty",
        "more_confident": "confident",
        "tease_lightly": "tease_lightly",
        "tease_lite": "tease_lightly",
    }
    return aliases.get(m, m)


@router.post("/escalation-drafts")
def escalation_drafts(
    payload: dict = Body(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Generate respectful escalation invitation drafts (voice/video/date).
    Never auto-sent. Returns text only; no message content is stored here.
    Tier gating:
    - premium_plus: slightly more personalized phrasing (still safe)
    - free/premium: simpler respectful drafts
    """
    plan = SubscriptionService().get_active_plan(db, current_user.id)
    plan_tier = plan if plan in {"free", "premium", "premium_plus"} else "free"
    kind = str(payload.get("kind") or "").strip().lower()
    if kind not in {"voice", "video", "date"}:
        raise HTTPException(status_code=400, detail="kind must be voice|video|date")
    match_name = str(payload.get("match_name") or "").strip()[:80]
    interests = payload.get("interests")
    interests_list = [str(x).strip()[:40] for x in interests] if isinstance(interests, list) else []
    interest = interests_list[0] if interests_list else ""

    # Safe, deterministic drafts (works for all providers; avoids latency loops).
    # Premium Plus gets slightly richer personalization.
    loc_raw = str(payload.get("locale") or payload.get("language") or "").strip()
    locale = normalize_ai_request_locale(loc_raw or "en")
    template_locale = locale if locale in {"uk", "ru", "en"} else "en"
    name = match_name
    if template_locale == "en":
        hi = f"Hi, {name} 🙂" if name else "Hi 🙂"
        topic = f" By the way, about {interest} —" if interest and plan_tier == "premium_plus" else ""
    elif template_locale == "ru":
        hi = f"Привет, {name} 🙂" if name else "Привет 🙂"
        topic = f" Кстати, про {interest} —" if interest and plan_tier == "premium_plus" else ""
    else:
        hi = f"Привіт, {name} 🙂" if name else "Привіт 🙂"
        topic = f" До речі, про {interest} —" if interest and plan_tier == "premium_plus" else ""

    if kind == "voice":
        drafts = (
            [
                f"{hi}{topic} want to swap a short voice note? It’s easier to catch the vibe.",
                f"{hi} If you’re comfortable, we could each send one voice note — no rush 🙂",
                f"{hi} I’d love to hear your voice. Would you send a quick voice note?",
            ]
            if template_locale == "en"
            else [
                f"{hi}{topic} хочеш обмінятися короткою голосовою? Так простіше відчути вайб."
                if template_locale == "uk"
                else f"{hi}{topic} хочешь обменяться короткой голосовой? Так проще почувствовать вайб.",
                f"{hi} Якщо тобі комфортно, можемо надіслати по одній голосовій — без поспіху 🙂"
                if template_locale == "uk"
                else f"{hi} Если тебе комфортно, можем отправить по одной голосовой — без спешки 🙂",
                f"{hi} Я б із задоволенням почув(ла) твій голос. Кинеш коротку голосову?"
                if template_locale == "uk"
                else f"{hi} Я бы с удовольствием услышал(а) твой голос. Скинешь короткую голосовую?",
            ]
        )
    elif kind == "video":
        drafts = (
            [
                f"{hi}{topic} how about a quick 10‑minute call today/tomorrow? No pressure.",
                f"{hi} If you want, we could hop on a short call — just to see if there’s chemistry 🙂",
                f"{hi} Talking to you feels easy. Want a quick video call when it’s convenient?",
            ]
            if template_locale == "en"
            else [
                f"{hi}{topic} як тобі ідея короткого дзвінка на 10 хв сьогодні/завтра? Без тиску."
                if template_locale == "uk"
                else f"{hi}{topic} как тебе идея короткого звонка на 10 мин сегодня/завтра? Без давления.",
                f"{hi} Якщо хочеш, можемо созвонитися на кілька хвилин — просто щоб відчути, чи є хімія 🙂"
                if template_locale == "uk"
                else f"{hi} Если хочешь, можем созвониться на пару минут — просто чтобы понять, есть ли химия 🙂",
                f"{hi} Мені з тобою легко. Хочеш короткий відеодзвінок, коли буде зручно?"
                if template_locale == "uk"
                else f"{hi} С тобой легко. Хочешь короткий видеозвонок, когда будет удобно?",
            ]
        )
    else:
        drafts = (
            [
                f"{hi}{topic} if you’re up for it, we could grab coffee this week 🙂",
                f"{hi} Coffee or a walk — what’s more your vibe? We can keep it simple and meet.",
                f"{hi} I like talking with you. If you’re open to it, let’s plan a low‑key meetup.",
            ]
            if template_locale == "en"
            else [
                f"{hi}{topic} якщо буде настрій, можемо зустрітися на каву цього тижня 🙂"
                if template_locale == "uk"
                else f"{hi}{topic} если будет настроение, можем встретиться на кофе на этой неделе 🙂",
                f"{hi} Ти як — більше за каву чи прогулянку? Можемо вибрати щось просте й зустрітися."
                if template_locale == "uk"
                else f"{hi} Ты больше за кофе или за прогулку? Можем выбрать что-то простое и встретиться.",
                f"{hi} З тобою цікаво. Якщо ти не проти — давай домовимось про зустріч без поспіху."
                if template_locale == "uk"
                else f"{hi} С тобой интересно. Если ты не против — давай договоримся о встрече без спешки.",
            ]
        )

    out = [d.strip() for d in drafts if d and d.strip()][: (3 if plan_tier == "premium_plus" else 2)]
    track_event(
        db,
        "escalation_drafts_generated",
        user_id=current_user.id,
        payload={"kind": kind, "plan_tier": plan_tier, "count": len(out), "locale": locale},
    )
    if out:
        track_event(
            db,
            "meeting_suggested",
            user_id=current_user.id,
            payload={"source": "escalation_drafts", "kind": kind, "plan_tier": plan_tier, "count": len(out), "locale": locale},
        )
    return {"drafts": out}


def _is_profile_verified_approved(profile: Profile | None) -> bool:
    return is_verified_profile(profile)


def _viewer_trust_bucket(db: Session, user_id: int) -> tuple[str, bool, bool]:
    """Backend-only trust derivation. Never trust frontend-provided flags."""
    p = db.query(Profile).filter(Profile.user_id == user_id).first()
    is_verified = _is_profile_verified_approved(p)
    try:
        q = compute_profile_quality(p) if p else None
        is_low_quality = bool(q and q.quality_flag == "low_quality")
    except Exception:
        is_low_quality = False
    bucket = "verified" if is_verified else ("low_quality" if is_low_quality else "normal")
    return bucket, is_verified, is_low_quality


def _get_ai_style_policy(*, plan_tier: str, is_verified: bool, is_low_quality: bool, requested_mode: str) -> dict:
    """Trust-aware policy for chat assist style/mode selection."""
    req = " ".join((requested_mode or "").strip().lower().split())
    effective = req

    # Defaults: keep existing behavior unless we need to clamp.
    personalization_level = "base"
    tone_guard_level = "standard"

    if is_low_quality:
        personalization_level = "low"
        tone_guard_level = "high"
        # Clamp advanced/edgy-ish modes to calmer defaults.
        lowq_map = {
            "flirty": "polish",
            "tease_lightly": "playful",
            "direct": "more_natural",
            "witty": "polish",
            "charming": "polish",
            "thoughtful": "polish",
            "confident": "polish",
            "softer": "more_natural",
            "romantic": "polish",
            "deep": "polish",
            "playful": "polish",
        }
        effective = lowq_map.get(req, req)

    if is_verified:
        personalization_level = "high" if plan_tier == "premium_plus" else "medium"
        # Do not relax safety; just allow richer expression where already allowed by plan.
        tone_guard_level = "standard"

    return {
        "allowed_modes": None,
        "downgraded_mode": effective if effective != req else None,
        "personalization_level": personalization_level,
        "tone_guard_level": tone_guard_level,
        "requested_mode": req,
        "effective_mode": effective,
    }

_INTEREST_LABELS = {
    "travel": "подорожі",
    "traveling": "подорожі",
    "travelling": "подорожі",
    "trips": "подорожі",
    "trip": "подорожі",
    "подорожі": "подорожі",
    "подорож": "подорожі",
    "подорожувати": "подорожі",
    "coffee": "кава",
    "coffee shops": "кава",
    "cafe": "кава",
    "кава": "кава",
    "кав'ярні": "кава",
    "music": "музика",
    "музика": "музика",
    "books": "книги",
    "book": "книги",
    "reading": "книги",
    "книги": "книги",
    "movies": "фільми",
    "movie": "фільми",
    "films": "фільми",
    "film": "фільми",
    "фільми": "фільми",
    "спорт": "спорт",
    "sport": "спорт",
    "fitness": "спорт",
    "йога": "спорт",
    "yoga": "спорт",
    "food": "їжа",
    "foodie": "їжа",
    "cooking": "їжа",
    "кухня": "їжа",
    "їжа": "їжа",
    "dogs": "собаки",
    "dog": "собаки",
    "собаки": "собаки",
    "cats": "коти",
    "cat": "коти",
    "коти": "коти",
}

_INTEREST_QUESTIONS = {
    "подорожі": "яка поїздка запам'яталась тобі найбільше?",
    "кава": "ти більше за затишну кав'ярню чи за каву з собою перед справами?",
    "музика": "що в тебе зараз на репіті?",
    "книги": "яка книга останнім часом реально зачепила?",
    "фільми": "який фільм ти б радила без довгих пояснень?",
    "спорт": "що тобі в цьому більше подобається: азарт чи відчуття ритму?",
    "їжа": "є страва або місце, куди ти готова повертатися без вагань?",
    "собаки": "у тебе є улюблена порода чи ти просто безумовно за собак?",
    "коти": "ти більше за незалежний котячий вайб чи за домашній затишок?",
}

_INTEREST_COMBOS = {
    frozenset({"подорожі", "кава"}): "У новому місті ти спершу шукаєш красивий маршрут чи класну кав'ярню?",
    frozenset({"подорожі", "їжа"}): "У поїздках тебе більше захоплює маршрут чи місцева кухня?",
    frozenset({"музика", "подорожі"}): "Є трек, який у тебе автоматично асоціюється з дорогою?",
}


def _normalize_style(style: str | None) -> str:
    key = " ".join((style or "").strip().lower().split())
    return _OPENER_STYLE_ALIASES.get(key, "playful")


def _is_plus(db: Session, user_id: int) -> bool:
    return SubscriptionService().get_active_plan(db, user_id) == "premium_plus"


def _normalize_interest(raw: str) -> str:
    return " ".join((raw or "").strip().lower().replace("_", " ").replace("-", " ").split())


def _clean_name(name: str) -> str:
    return " ".join((name or "").strip().split())


def _dedupe_preserve_order(items: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        key = " ".join((item or "").strip().lower().split())
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(" ".join((item or "").strip().split()))
    return out


def _map_interest_label(raw: str) -> str | None:
    token = _normalize_interest(raw)
    if not token:
        return None
    if token in _INTEREST_LABELS:
        return _INTEREST_LABELS[token]
    return token[:40]


def _interest_question(topic: str) -> str:
    return _INTEREST_QUESTIONS.get(topic, f"що в цьому тебе чіпляє найбільше?")


def _combo_question(primary: str, secondary: str) -> str:
    combo = _INTEREST_COMBOS.get(frozenset({primary, secondary}))
    if combo:
        return combo
    return f"Що з цього для тебе перемагає, якщо часу тільки на одне: {primary} чи {secondary}?"


def _interest_labels(interests: list[str], bio: str) -> list[str]:
    labels: list[str] = []
    seen: set[str] = set()

    for raw in interests or []:
        label = _map_interest_label(raw)
        if label and label not in seen:
            seen.add(label)
            labels.append(label)

    bio_lc = (bio or "").lower()
    for alias, label in _INTEREST_LABELS.items():
        if alias in bio_lc and label not in seen:
            seen.add(label)
            labels.append(label)

    return labels[:3]


def _fallback_opener_candidates(name: str, style: str, primary_topic: str | None) -> list[str]:
    greeting = f"Привіт, {name}" if name else "Привіт"
    candidates = [
        f"{greeting}! Якщо зараз дати тобі квиток будь-куди, куди полетиш?",
        "Маленьке не-банальне питання: що тебе останнім часом реально потішило?",
        "З чого з тобою краще починати розмову: історії, жарти чи плани на вихідні?",
        f"{greeting}! Що про тебе найважче вгадати з першого повідомлення?",
    ]
    if primary_topic:
        candidates.insert(0, f"{greeting}, якщо коротко: що в {primary_topic} тебе чіпляє найбільше?")

    if style in {"confident", "direct"}:
        candidates.append(f"{greeting}. Без банальностей: що зараз у тебе в житті найцікавіше?")
    elif style == "curious":
        candidates.append(f"{greeting}. Яка тема може затягнути тебе в розмову надовго?")
    elif style == "flirty":
        candidates.append(f"{greeting} 🙂 якщо я вгадаю твій вайб за одним питанням, яке воно буде?")
    elif style == "witty":
        candidates.append(f"{greeting}. Окей, швидка гра: два факти і одна вигадка — що обереш?")
    elif style == "charming":
        candidates.append(f"{greeting}. У тебе дуже приємний вайб. Який маленький момент робить день кращим?")
    elif style == "thoughtful":
        candidates.append(f"{greeting}. Що для тебе в розмовах найцінніше — легкість, чесність чи гумор?")
    elif style == "tease_lightly":
        candidates.append(f"{greeting} 😄 якщо я напишу банальне «як справи?», ти мене пробачиш чи ні?")
    else:
        candidates.append(f"{greeting} 🙂 який у тебе ідеальний спонтанний вечір?")

    return _dedupe_preserve_order(candidates)


def _generate_opener_candidates(req: GenerateOpenerSuggestionsRequest) -> list[str]:
    name = _clean_name(req.match_name)
    bio = " ".join((req.bio or "").strip().split())
    style = _normalize_style(req.style)
    topics = _interest_labels(req.interests, bio)
    primary = topics[0] if topics else None
    secondary = topics[1] if len(topics) > 1 else None
    greeting = f"Привіт, {name}" if name else "Привіт"

    candidates: list[str] = []

    if primary:
        if style in {"confident", "direct"}:
            candidates.append(f"{greeting}. У тебе в профілі одразу зачепили {primary}. {_interest_question(primary).capitalize()}")
        elif style == "curious":
            candidates.append(f"{greeting}, бачу, тобі близькі {primary}. {_interest_question(primary).capitalize()}")
        elif style == "flirty":
            candidates.append(f"{greeting} 🙂 {primary} — це вже плюс у карму. {_interest_question(primary).capitalize()}")
        elif style == "witty":
            candidates.append(f"{greeting}. {primary.capitalize()} — ок, зараховано. Питання на кмітливість: {_interest_question(primary)}")
        elif style == "charming":
            candidates.append(f"{greeting}! {primary.capitalize()} у тебе звучить дуже красиво. {_interest_question(primary).capitalize()}")
        elif style == "thoughtful":
            candidates.append(f"{greeting}. {primary.capitalize()} часто багато про людину говорить. {_interest_question(primary).capitalize()}")
        elif style == "tease_lightly":
            candidates.append(f"{greeting} 😄 {primary} — неочікувано. {_interest_question(primary).capitalize()}")
        else:
            candidates.append(f"{greeting} 🙂 бачу, тобі близькі {primary} — {_interest_question(primary)}")

    if primary and secondary:
        if style in {"playful", "tease_lightly"}:
            candidates.append(f"{primary.capitalize()} і {secondary} — це вже дуже хороший набір 😄 {_combo_question(primary, secondary)}")
        elif style == "witty":
            candidates.append(f"{primary.capitalize()} + {secondary} — це як трейлер до класної історії. {_combo_question(primary, secondary)}")
        else:
            candidates.append(f"{primary.capitalize()} і {secondary} у тебе звучать як сильне комбо. {_combo_question(primary, secondary)}")
    elif primary:
        candidates.append(f"{primary.capitalize()} у тебе явно не для галочки. Що в цьому для тебе найцікавіше?")

    if bio:
        if style in {"confident", "direct"}:
            candidates.append(f"{greeting}. Помітила кілька деталей про тебе — що зараз у фокусі: робота, відпочинок чи щось третє?")
        elif style == "curious":
            candidates.append(f"{greeting}. По твоїх рядках відчувається затишний вайб — що тебе зараз реально надихає?")
        elif style == "flirty":
            candidates.append(f"{greeting} 🙂 чесно: від твоїх рядків хочеться усміхнутись. Що тебе зараз найбільше заряджає?")
        elif style == "witty":
            candidates.append(f"{greeting}. Якщо твій опис — це трейлер, який жанр повного фільму? 😄")
        elif style == "charming":
            candidates.append(f"{greeting}! Який момент з останнього тижня був найприємнішим?")
        elif style == "thoughtful":
            candidates.append(f"{greeting}. Чую щирість у тому, як ти себе описала — що для тебе зараз важливо в житті?")
        elif style == "tease_lightly":
            candidates.append(f"{greeting} 😄 Чим тебе найкраще можна підкупити — кавою чи історією?")
        else:
            candidates.append(f"{greeting}! Що з останнього тижня принесло тобі найбільше емоцій?")

    candidates.extend(_fallback_opener_candidates(name, style, primary))
    return _dedupe_preserve_order(candidates)


def _safe_opener_suggestions(req: GenerateOpenerSuggestionsRequest) -> list[str]:
    name = _clean_name(req.match_name)
    style = _normalize_style(req.style)
    bio = " ".join((req.bio or "").strip().split())
    topics = _interest_labels(req.interests, bio)
    primary = topics[0] if topics else None

    suggestions: list[str] = []
    seen: set[str] = set()

    for row in filter_chat_suggestions(kind="openers", candidates=_generate_opener_candidates(req), partner_name=name or None):
        key = row.text.lower()
        if key in seen:
            continue
        seen.add(key)
        suggestions.append(row.text)
        if len(suggestions) == 3:
            return suggestions

    rescue_candidates = _fallback_opener_candidates(name, style, primary) + [
        f"{'Привіт, ' + name if name else 'Привіт'}! Яке питання про тебе точно не звучить банально?",
        "Якщо без банальностей: що зараз у тебе в житті найцікавіше?",
        "Що в тобі люди зазвичай помічають не одразу, а дарма?",
    ]
    for row in filter_chat_suggestions(kind="openers", candidates=rescue_candidates, partner_name=name or None):
        key = row.text.lower()
        if key in seen:
            continue
        seen.add(key)
        suggestions.append(row.text)
        if len(suggestions) == 3:
            return suggestions

    return suggestions[:3]

@router.get("/icebreakers/{target_user_id}")
def icebreakers(target_user_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not settings.ENABLE_AI_SUGGESTIONS:
        return {"suggestions": ["AI suggestions are currently disabled."]}
    # Free tier: 1 opener/day. Premium: unlimited.
    try:
        plan = SubscriptionService().get_active_plan(db, int(current_user.id))
    except Exception:
        plan = "free"
    if plan not in {"premium", "premium_plus"}:
        st = _daily_boosts_get(db, user_id=int(current_user.id))
        if bool(st.get("opener_used")):
            raise HTTPException(status_code=402, detail=api_error("paywall.ai_opener_daily_limit", max=1))
        _daily_boosts_consume(db, user_id=int(current_user.id), boost_type="opener")
    try:
        enforce_ai_limits(db, current_user.id)
    except RateLimitExceeded:
        return {"suggestions": []}
    my_profile = db.query(Profile).filter(Profile.user_id == current_user.id).first()
    other_profile = db.query(Profile).filter(Profile.user_id == target_user_id).first()
    if not other_profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    from app.services.ai.orchestrator import AIOrchestrator

    return {"suggestions": AIOrchestrator.generate_icebreakers(my_profile=my_profile, other_profile=other_profile)}

@router.post("/reply-suggestions")
def reply_suggestions(payload: dict = Body(...), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not settings.ENABLE_AI_SUGGESTIONS:
        return {"suggestions": ["AI suggestions are currently disabled."]}
    if settings.ENABLE_PREMIUM_FEATURES and not has_premium_access(db, current_user.id, "unlimited_ai_suggestions"):
        return {"suggestions": ["Upgrade to premium for advanced AI suggestions."]}
    try:
        enforce_ai_limits(db, current_user.id)
    except RateLimitExceeded:
        return {"suggestions": []}
    my_profile = db.query(Profile).filter(Profile.user_id == int(current_user.id)).first()
    from app.services.ai.orchestrator import AIOrchestrator

    ui_loc = payload.get("locale") or payload.get("language")
    return {
        "suggestions": AIOrchestrator.generate_reply_suggestions(
            last_message=str(payload.get("last_message", "") or ""),
            me=my_profile,
            ui_locale=str(ui_loc).strip() if ui_loc else None,
        )
    }


@router.post("/chat-brain/suggestions")
def chat_brain_suggestions(
    body: ChatBrainRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return 3 safe variants (light / flirty / deep) for the current user's chat with partner_user_id."""
    pid = int(body.partner_user_id)
    if is_blocked(db, current_user.id, pid):
        raise HTTPException(status_code=403, detail=api_error("chat.user_blocked"))
    if not users_are_matched(db, current_user.id, pid):
        raise HTTPException(status_code=403, detail=api_error("chat.match_required"))
    raw_ui_lang = getattr(body, "language", None)
    partner_last_plain = _last_partner_message_plain(db, me_user_id=int(current_user.id), partner_user_id=pid)
    body.language = _resolve_ai_locale_for_request(
        req_locale=str(raw_ui_lang or "").strip() or None,
        ai_locale=getattr(body, "ai_locale", None),
        request=request,
        db=db,
        current_user=current_user,
        latest_user_message=partner_last_plain,
        prefer_message_locale=False,
        route_label="POST /ai/chat-brain/suggestions",
    )
    lang_hint_in = str(getattr(body, "language_hint", None) or "").strip() or None
    norm_for_log = normalize_chat_ai_locale(getattr(body, "language", None) or "en")
    log_ai_locale_context(
        logger,
        endpoint="chat-brain/suggestions",
        ui_locale=str(raw_ui_lang).strip() if raw_ui_lang is not None else None,
        ai_locale=norm_for_log,
        language_hint=lang_hint_in,
        source="request",
        fallback_used=False,
    )
    logger.info("AI locale used: %s", norm_for_log)
    if not settings.ENABLE_AI_SUGGESTIONS:
        lang = normalize_chat_ai_locale(getattr(body, "language", None) or "en")
        partner_name = _display_name(db, pid)
        variants = chat_brain_fallback_pack(
            str(getattr(body, "mode", "auto")), partner_name, lang, last_partner_message=partner_last_plain or None
        )
        variants = _guard_uk_chat_brain_response_variants(lang, variants, partner_last_plain)
        plan = SubscriptionService().get_active_plan(db, current_user.id)
        plan_tier_pre = plan if plan in {"free", "premium", "premium_plus"} else "free"
        log_ai_fallback_triggered(
            endpoint="chat-brain/suggestions",
            locale=lang,
            reason="ai_suggestions_disabled",
            error_message="ENABLE_AI_SUGGESTIONS=false",
            provider="gemini",
        )
        return {
            "ok": True,
            "variants": variants,
            "coaching": {"action": "write_now"},
            "ui": {"suggestions_visible": True},
            "recommended_variant": "light",
            "recommendation_reason": "invites_reply",
            "variant_insights": {},
            "meta": {"mode": "auto", "language": lang, "ai_used": False, "plan_tier": plan_tier_pre},
            "locale": lang,
            "source": "fallback",
            "fallback": True,
        }
    try:
        plan_tier_pre, _ = enforce_and_consume_ai_usage(db, user_id=int(current_user.id), usage_type="message")
    except AiNotUnlocked:
        _raise_ai_unlock_after_match()
    except AiLimitReached:
        _raise_ai_limit_hit()
    except AiRapidCooldown:
        lang = normalize_chat_ai_locale(getattr(body, "language", None))
        partner_name = _display_name(db, pid)
        variants = chat_brain_fallback_pack(
            str(getattr(body, "mode", "auto")), partner_name, lang, last_partner_message=partner_last_plain or None
        )
        variants = _guard_uk_chat_brain_response_variants(lang, variants, partner_last_plain)
        logger.info("chat_ai_fallback_used", extra={"endpoint": "chat-brain/suggestions", "reason": "spam_cooldown", "locale": lang})
        return {
            "ok": True,
            "variants": variants,
            "coaching": {"action": "write_now"},
            "ui": {"suggestions_visible": True},
            "recommended_variant": "light",
            "recommendation_reason": "invites_reply",
            "variant_insights": {},
            "meta": {"mode": "auto", "language": lang, "ai_used": False, "plan_tier": plan_tier_pre},
            "locale": lang,
            "source": "fallback",
        }
    try:
        if plan_tier_pre == "free" and bool(getattr(settings, "AI_STRICT_MONETIZATION", False)) and not bool(os.getenv("PYTEST_CURRENT_TEST")):
            lang = normalize_chat_ai_locale(getattr(body, "language", None))
            partner_name = _display_name(db, pid)
            variants = chat_brain_fallback_pack(
                str(getattr(body, "mode", "auto")), partner_name, lang, last_partner_message=partner_last_plain or None
            )
            variants = _guard_uk_chat_brain_response_variants(lang, variants, partner_last_plain)
            return {
                "ok": True,
                "variants": variants,
                "coaching": {"action": "write_now"},
                "ui": {"suggestions_visible": True},
                "recommended_variant": "light",
                "recommendation_reason": "invites_reply",
                "variant_insights": {},
                "meta": {"mode": "auto", "language": lang, "ai_used": False, "plan_tier": plan_tier_pre},
                "locale": lang,
                "source": "fallback",
            }
        enforce_ai_limits(db, current_user.id)
    except RateLimitExceeded:
        # Never hide the panel on rate limit: return localized safe fallback (HTTP 200).
        lang = normalize_chat_ai_locale(getattr(body, "language", None))
        partner_name = _display_name(db, pid)
        variants = chat_brain_fallback_pack(
            str(getattr(body, "mode", "auto")), partner_name, lang, last_partner_message=partner_last_plain or None
        )
        variants = _guard_uk_chat_brain_response_variants(lang, variants, partner_last_plain)
        logger.info("chat_ai_fallback_used", extra={"endpoint": "chat-brain/suggestions", "reason": "rate_limited", "locale": lang, "plan_tier": plan_tier_pre})
        fb_meta = {"mode": "auto", "language": lang, "ai_used": False, "plan_tier": plan_tier_pre}
        track_event(
            db,
            "ai_suggestion_shown",
            user_id=current_user.id,
            payload={
                "mode": "auto",
                "language": lang,
                "partner_user_id": pid,
                "ai_used": False,
                "recommended_variant": "light",
                "coaching_action": "write_now",
                "source": "fallback_rate_limited",
                "topic_detected": None,
                "topic_confidence": None,
                "conversation_stage": None,
                "conversation_mode": None,
            },
        )
        track_event(
            db,
            "stage_detected",
            user_id=current_user.id,
            payload={
                "partner_user_id": pid,
                "conversation_stage": None,
                "conversation_mode": None,
                "mode": "auto",
                "source": "chat_brain_fallback",
            },
        )
        mark_ai_suggestion_wave(
            current_user.id,
            pid,
            {
                "partner_user_id": pid,
                "conversation_stage": None,
                "conversation_mode": None,
                "mode": "auto",
                "recommended_variant": "light",
                "source": "fallback_rate_limited",
            },
        )
        return {
            "ok": True,
            "variants": variants,
            "coaching": {"action": "write_now"},
            "ui": {"suggestions_visible": True},
            "recommended_variant": "light",
            "recommendation_reason": "invites_reply",
            "variant_insights": {},
            "meta": fb_meta,
            "locale": lang,
            "source": "fallback",
        }
    plan_tier = plan_tier_pre
    # Normalize language to supported app language (en/uk/ru/pt/es/ja/...).
    body.language = normalize_chat_ai_locale(getattr(body, "language", None))
    from app.services.ai.orchestrator import AIOrchestrator

    out = AIOrchestrator.generate_chat_brain_pack(db=db, user_id=current_user.id, body=body, plan_tier=plan_tier)
    if not out.get("ok"):
        raise HTTPException(status_code=400, detail=out)
    lang_resp = normalize_chat_ai_locale(str((out.get("meta") or {}).get("language") or body.language or "en"))
    try:
        _pp_dbg = db.query(Profile).filter(Profile.user_id == int(current_user.id)).first()
        _prof_dbg = str(getattr(_pp_dbg, "preferred_language", "") or "").strip() if _pp_dbg else ""
    except Exception:
        _prof_dbg = ""
    try:
        from app.services.ai.output_script_locale import sniff_dominant_script_for_log

        _vb = out.get("variants") or {}
        _brain_guess = sniff_dominant_script_for_log(
            " ".join(str(_vb.get(k) or "") for k in ("light", "flirty", "deep"))
        )
    except Exception:
        _brain_guess = None
    log_ai_response_debug(
        route="POST /ai/chat-brain/suggestions",
        resolved_locale=str(body.language or ""),
        profile_locale=_prof_dbg or None,
        request_locale=str(raw_ui_lang or "").strip() or None,
        accept_language=request.headers.get("accept-language") if request else None,
        final_language=lang_resp,
        fallback_used=not bool((out.get("meta") or {}).get("ai_used")),
        cache_hit=False,
        output_language_guess=_brain_guess,
    )
    if isinstance(out.get("variants"), dict):
        out["variants"] = _guard_uk_chat_brain_response_variants(
            lang_resp, out["variants"], partner_last_plain
        )
    meta = out.get("meta") or {}
    coaching = out.get("coaching") or {}
    track_event(
        db,
        "ai_suggestion_shown",
        user_id=current_user.id,
        payload={
            "mode": str(meta.get("mode") or ""),
            "language": str(meta.get("language") or ""),
            "partner_user_id": pid,
            "regenerate_variant": meta.get("regenerate_variant"),
            "ai_used": bool(meta.get("ai_used")),
            "recommended_variant": out.get("recommended_variant"),
            "coaching_action": coaching.get("action"),
            "coaching_hint": coaching.get("hint_key"),
            "premium_teaser": coaching.get("premium_teaser_key"),
            "mode_resolution": meta.get("mode_resolution"),
            "suggestions_visible": (out.get("ui") or {}).get("suggestions_visible"),
            "topic_detected": meta.get("topic"),
            "topic_confidence": meta.get("topic_confidence"),
            "conversation_stage": meta.get("conversation_stage"),
            "conversation_mode": meta.get("conversation_mode"),
            "premium_mode_used": bool(meta.get("premium_mode_used")),
            "context_messages_limit": meta.get("context_messages_limit"),
        },
    )
    track_event(
        db,
        "stage_detected",
        user_id=current_user.id,
        payload={
            "partner_user_id": pid,
            "conversation_stage": meta.get("conversation_stage"),
            "conversation_mode": meta.get("conversation_mode"),
            "mode": str(meta.get("mode") or ""),
            "topic": meta.get("topic"),
            "source": "chat_brain",
        },
    )
    mark_ai_suggestion_wave(
        current_user.id,
        pid,
        {
            "partner_user_id": pid,
            "conversation_stage": meta.get("conversation_stage"),
            "conversation_mode": meta.get("conversation_mode"),
            "mode": str(meta.get("mode") or ""),
            "recommended_variant": out.get("recommended_variant"),
            "source": "chat_brain",
        },
    )
    if bool(getattr(settings, "AI_STRICT_MONETIZATION", False)) and not bool(os.getenv("PYTEST_CURRENT_TEST")):
        variants_raw = out.get("variants") or {}
        if isinstance(variants_raw, dict):
            for k in ("light", "flirty", "deep"):
                txt = str(variants_raw.get(k) or "").strip()
                if txt:
                    variants_raw[k] = _ensure_question_short(txt)
            out["variants"] = variants_raw
    # Always include locale+source for frontend UX.
    out["locale"] = str((out.get("meta") or {}).get("language") or body.language or "en")
    out["source"] = "ai" if (out.get("meta") or {}).get("ai_used") else "fallback"
    return out


def _coach_public_risk(stall_risk: int) -> str:
    if int(stall_risk) >= 68:
        return "high"
    if int(stall_risk) >= 38:
        return "medium"
    return "low"


def _coach_advice_text(move: str, *, locale: str) -> str:
    return coach_advice_for_move(move, locale=locale)


@router.get("/coach/next-move")
def coach_next_move(
    partner_user_id: int,
    locale: str | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    pid = int(partner_user_id)
    if pid <= 0 or pid == int(current_user.id):
        raise HTTPException(status_code=400, detail=api_error("chat.invalid_match"))
    if is_blocked(db, current_user.id, pid):
        raise HTTPException(status_code=403, detail=api_error("chat.user_blocked"))
    if not users_are_matched(db, current_user.id, pid):
        raise HTTPException(status_code=403, detail=api_error("chat.match_required"))

    plan = SubscriptionService().get_active_plan(db, current_user.id)
    plan_tier = plan if plan in {"free", "premium", "premium_plus"} else "free"
    loc = normalize_chat_ai_locale(locale or "en")
    limit = 100 if plan_tier == "premium_plus" else 50 if plan_tier == "premium" else 12
    rows = (
        db.query(Message)
        .filter(
            or_(
                and_(Message.sender_id == int(current_user.id), Message.receiver_id == pid),
                and_(Message.sender_id == pid, Message.receiver_id == int(current_user.id)),
            )
        )
        .order_by(Message.created_at.desc())
        .limit(limit)
        .all()
    )
    messages = [
        {
            "role": "me" if int(m.sender_id) == int(current_user.id) else "partner",
            "text": str(m.content or ""),
            "created_at": m.created_at,
        }
        for m in reversed(rows)
        if str(m.content or "").strip()
    ]
    me_profile = db.query(Profile).filter(Profile.user_id == int(current_user.id)).first()
    partner_profile = db.query(Profile).filter(Profile.user_id == pid).first()
    memory = build_memory_context_for_prompt(db, user_id=int(current_user.id), partner_user_id=pid) if plan_tier in {"premium", "premium_plus"} else {}
    from app.services.ai.orchestrator import AIOrchestrator

    score = AIOrchestrator.generate_coach_score(
        last_messages=messages,
        current_user_profile=me_profile,
        partner_profile=partner_profile,
        memory=memory,
        locale=loc,
    )
    move = str(score.get("recommended_move") or "reply")
    is_premium = plan_tier in {"premium", "premium_plus"}
    should_wait = move == "wait" or int(score.get("stall_risk") or 0) >= 78
    out: dict[str, Any] = {
        "advice": _coach_advice_text(move, locale=loc),
        "recommended_tone": "calm" if should_wait else "playful" if move == "flirt" else "warm",
        "suggested_reply_style": "revive" if move == "revive" else "soft_meet" if move == "suggest_meet" else move,
        "send_timing": "wait" if should_wait else "send_now",
        "should_wait": bool(should_wait),
        "risk": _coach_public_risk(int(score.get("stall_risk") or 0)),
        "meeting_readiness": score.get("meeting_readiness_meta", "not_ready"),
        "plan_tier": plan_tier,
    }
    if is_premium:
        out["coach"] = score
        out["why_this_works"] = score.get("reason", "")
    if plan_tier == "premium_plus":
        out["proactive_reengage"] = move == "revive" or int(score.get("stall_risk") or 0) >= 65
    return out


@router.get("/profile-analysis/me")
def profile_analysis(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    profile = db.query(Profile).filter(Profile.user_id == current_user.id).first()
    return ProfileAI.analyze(profile)


def _map_opener_recommended_index(candidates: list[str], safe_texts: list[str], rec_idx: int) -> int:
    if not safe_texts:
        return 0
    rec_idx = max(0, min(rec_idx, 2))
    if not candidates:
        return 0
    rec_idx = min(rec_idx, len(candidates) - 1)
    chosen = (candidates[rec_idx] or "").strip()
    if not chosen:
        return 0
    try:
        return safe_texts.index(chosen)
    except ValueError:
        for i, st in enumerate(safe_texts):
            st = (st or "").strip()
            if not st:
                continue
            if chosen in st or st in chosen:
                return i
        return 0


_OPENER_TYPES_ORDER: tuple[str, ...] = ("safe", "flirty", "smart")


def _typed_fallback_openers(locale: str | None) -> list[tuple[str, str]]:
    return opener_typed_fallback(locale)


def generate_fallback_openers(locale: str | None) -> list[str]:
    return [text for _, text in _typed_fallback_openers(locale)]


def _opener_has_question_or_choice(text: str) -> bool:
    s = (text or "").strip()
    if not s:
        return False
    if "?" in s:
        return True
    low = f" {s.lower()} "
    for needle in (" чи ", " або ", " или ", " or ", " vs ", " vs. "):
        if needle in low:
            return True
    return False


def _coerce_provider_opener_rows(rows: list | None) -> list[dict[str, str]]:
    by_type: dict[str, str] = {}
    legacy: list[str] = []
    if isinstance(rows, list):
        for item in rows:
            if isinstance(item, dict):
                ot = str(item.get("type") or "").strip().lower()
                tx = str(item.get("text") or "").strip()
                if ot in _OPENER_TYPES_ORDER and tx:
                    if ot not in by_type:
                        by_type[ot] = tx
                elif tx:
                    legacy.append(tx)
            else:
                tx = str(item or "").strip()
                if tx:
                    legacy.append(tx)
    qi = 0
    out: list[dict[str, str]] = []
    for ot in _OPENER_TYPES_ORDER:
        tx = (by_type.get(ot) or "").strip()
        if not tx and qi < len(legacy):
            tx = legacy[qi].strip()
            qi += 1
        out.append({"type": ot, "text": tx})
    return out


def _finalize_typed_opener_items(
    typed: list[dict[str, str]],
    *,
    partner_name: str | None,
    locale: str | None,
) -> list[dict[str, str]]:
    from app.services.ai.ai_request_locale import normalize_ai_request_locale
    from app.services.ai.output_script_locale import text_matches_requested_locale

    fallback_map = dict(_typed_fallback_openers(locale))
    used_lower: set[str] = set()
    out: list[dict[str, str]] = []
    loc = normalize_ai_request_locale(locale)

    for row in typed:
        ot = str(row.get("type") or "").strip().lower()
        if ot not in _OPENER_TYPES_ORDER:
            ot = "safe"
        text = _sanitize(str(row.get("text") or ""), 220)
        if text:
            fr = filter_chat_suggestions(kind="openers", candidates=[text], partner_name=partner_name)
            text = fr[0].text if fr else ""
        fb = fallback_map.get(ot) or fallback_map["safe"]
        if not text or not _opener_has_question_or_choice(text):
            text = _sanitize(fb, 220)
            fr = filter_chat_suggestions(kind="openers", candidates=[text], partner_name=partner_name)
            text = fr[0].text if fr else fb
        if not text_matches_requested_locale(text, loc):
            text = _sanitize(fb, 220)
            fr = filter_chat_suggestions(kind="openers", candidates=[text], partner_name=partner_name)
            text = fr[0].text if fr else fb
        low = text.lower()
        if low in used_lower:
            text = fb
            low = text.lower()
        used_lower.add(low)
        if not _opener_has_question_or_choice(text):
            text = fb
        out.append({"type": ot, "text": text})
    return out


def _finalize_opener_suggestions(*, suggestions: list[str] | None, locale: str | None) -> list[str]:
    """Legacy string-only finalize: dedupe, pad to 3 using locale-aware forced-choice lines."""
    raw = suggestions or []
    out: list[str] = []
    seen: set[str] = set()
    for s in raw:
        tx = _avoid_generic_hi(str(s or "").strip(), locale)
        if not tx:
            continue
        if not _opener_has_question_or_choice(tx):
            tx = _ensure_question_short(tx)
        key = tx.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(tx[:280])
        if len(out) >= 3:
            break

    if len(out) >= 3:
        return out[:3]

    for s in generate_fallback_openers(locale):
        tx = _avoid_generic_hi(str(s or "").strip(), locale)
        if not tx:
            continue
        if not _opener_has_question_or_choice(tx):
            tx = _ensure_question_short(tx)
        key = tx.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(tx[:280])
        if len(out) >= 3:
            break

    if len(out) < 3:
        out = generate_fallback_openers(locale)[:3]
    return out[:3]


@router.post("/opener", response_model=GenerateOpenerSuggestionsResponse)
async def opener_suggestions(
    req: GenerateOpenerSuggestionsRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    raw_ui = getattr(req, "locale", None)
    latest_user_message = ""
    try:
        latest_user_message = next((str(x or "").strip() for x in reversed(req.conversation_context or []) if str(x or "").strip()), "")
    except Exception:
        latest_user_message = ""
    req.locale = _resolve_ai_locale_for_request(
        req_locale=raw_ui,
        ai_locale=getattr(req, "ai_locale", None),
        request=request,
        db=db,
        current_user=current_user,
        latest_user_message=latest_user_message,
        prefer_message_locale=False,
        route_label="POST /ai/opener",
    )
    log_ai_locale_context(logger, endpoint="opener", ui_locale=raw_ui, ai_locale=req.locale)
    logger.info("AI locale used: %s", req.locale)

    try:
        plan_tier, _ = enforce_and_consume_ai_usage(db, user_id=int(current_user.id), usage_type="opener")
    except AiNotUnlocked:
        _raise_ai_unlock_after_match()
    except AiLimitReached:
        _raise_ai_limit_hit()
    except AiRapidCooldown:
        plan_tier = "free"
    trust_bucket, viewer_is_verified, viewer_is_low_quality = _viewer_trust_bucket(db, current_user.id)
    partner_nm = _clean_name(req.match_name) or None
    opener_tags = [_sanitize(str(x or ""), 40) for x in (req.tags or []) if str(x or "").strip()][:12]
    opener_city = " ".join(_sanitize(str(req.city or ""), 120).strip().split())

    if plan_tier == "free" and bool(getattr(settings, "AI_STRICT_MONETIZATION", False)) and not bool(os.getenv("PYTEST_CURRENT_TEST")):
        from app.services.ai.locale_rewrite import batch_translate_lines

        fb_typed = _finalize_typed_opener_items(
            [{"type": t, "text": ""} for t in _OPENER_TYPES_ORDER],
            partner_name=partner_nm,
            locale=req.locale,
        )
        if normalize_ai_request_locale(req.locale) != "en":
            try:
                to_tr = [x["text"] for x in fb_typed]
                translated = await batch_translate_lines(to_tr, req.locale)
                if len(translated) == len(fb_typed):
                    for i, row in enumerate(fb_typed):
                        row["text"] = translated[i]
            except Exception:
                pass
        suggestions = [x["text"] for x in fb_typed]
        logger.warning("ai_opener_fallback_used", extra={"locale": (req.locale or "")})
        logger.info(
            "ai_assist_opener limited",
            extra={
                "provider_used": "fallback",
                "fallback_reason": "rate_limited",
                "trust_bucket": trust_bucket,
                "requested_mode": (req.style or ""),
                "effective_mode": (req.style or ""),
                "plan_tier": plan_tier,
            },
        )
        if plan_tier == "free":
            _daily_boosts_consume(db, user_id=int(current_user.id), boost_type="opener")
        return {"items": fb_typed, "suggestions": suggestions, "recommended_index": 1}
    try:
        enforce_ai_limits(db, current_user.id)
    except RateLimitExceeded:
        from app.services.ai.locale_rewrite import batch_translate_lines

        fb_typed = _finalize_typed_opener_items(
            [{"type": t, "text": ""} for t in _OPENER_TYPES_ORDER],
            partner_name=partner_nm,
            locale=req.locale,
        )
        if normalize_ai_request_locale(req.locale) != "en":
            try:
                to_tr = [x["text"] for x in fb_typed]
                translated = await batch_translate_lines(to_tr, req.locale)
                if len(translated) == len(fb_typed):
                    for i, row in enumerate(fb_typed):
                        row["text"] = translated[i]
            except Exception:
                pass
        suggestions = [x["text"] for x in fb_typed]
        logger.warning("ai_opener_fallback_used", extra={"locale": (req.locale or "")})
        logger.info(
            "ai_assist_opener limited",
            extra={
                "provider_used": "fallback",
                "fallback_reason": "rate_limited",
                "trust_bucket": trust_bucket,
                "requested_mode": (req.style or ""),
                "effective_mode": (req.style or ""),
                "plan_tier": plan_tier,
            },
        )
        return {"items": fb_typed, "suggestions": suggestions, "recommended_index": 1}

    requested_style = " ".join((req.style or "").strip().lower().split())
    normalized = _normalize_style(requested_style)
    if normalized in _PLUS_OPENER_STYLES and not _is_plus(db, current_user.id):
        normalized = "playful"
    policy = _get_ai_style_policy(
        plan_tier=plan_tier,
        is_verified=viewer_is_verified,
        is_low_quality=viewer_is_low_quality,
        requested_mode=normalized,
    )
    effective_style = str(policy.get("effective_mode") or normalized)
    if effective_style in _PLUS_OPENER_STYLES and not _is_plus(db, current_user.id):
        effective_style = "playful"
    # Make sure we stay within known opener styles.
    if effective_style not in (set(_OPENER_STYLE_ALIASES.values()) | _PLUS_OPENER_STYLES):
        effective_style = "playful"
    req.style = effective_style

    # Learning hint: use aggregate-only message outcomes to steer tone/length.
    try:
        from app.models.user_ai_memory import UserAiMemory

        row = (
            db.query(UserAiMemory)
            .filter(UserAiMemory.user_id == int(current_user.id), UserAiMemory.memory_type == "conversation_patterns", UserAiMemory.key == "message_outcomes")
            .first()
        )
        learned = (row.value_json or {}) if row else {}
        pref_tone = str(learned.get("preferred_tone") or "").strip().lower()
        pref_len = str(learned.get("preferred_length") or "").strip().lower()
        hint_parts = []
        if pref_len in {"short", "medium", "long"}:
            hint_parts.append(f"length={pref_len}")
        if pref_tone in {"playful", "serious"}:
            hint_parts.append(f"tone={pref_tone}")
        if hint_parts:
            ctx = list(req.conversation_context or [])
            ctx.append("LEARNING_HINT: " + " ".join(hint_parts))
            req.conversation_context = ctx[-12:]
    except Exception:
        pass

    from app.services.ai.orchestrator import AIOrchestrator

    out = await AIOrchestrator.complete_typed_opener_request(
        req=req,
        partner_nm=partner_nm,
        opener_city=opener_city,
        opener_tags=opener_tags,
        plan_tier=plan_tier,
        trust_bucket=trust_bucket,
        normalized=normalized,
    )
    try:
        items = out.get("items") if isinstance(out, dict) else None
        if isinstance(items, list):
            texts = [str((row or {}).get("text") if isinstance(row, dict) else "").strip() for row in items]
            fixed = await _enforce_ai_texts_locale_once(texts, locale=req.locale)
            for i, row in enumerate(items):
                if isinstance(row, dict) and i < len(fixed):
                    row["text"] = fixed[i]
            out["suggestions"] = [str(x or "").strip() for x in fixed]
    except Exception:
        pass
    if plan_tier == "free" and bool(getattr(settings, "AI_STRICT_MONETIZATION", False)) and not bool(os.getenv("PYTEST_CURRENT_TEST")):
        _daily_boosts_consume(db, user_id=int(current_user.id), boost_type="opener")
    return out


@router.post("/openers/{target_user_id}")
async def wingman_openers(
    target_user_id: int,
    req: GenerateOpenersRequest = Body(default_factory=GenerateOpenersRequest),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not settings.ENABLE_AI_SUGGESTIONS:
        return {"openers": [], "meta": {"limited": True}}
    try:
        enforce_ai_limits(db, current_user.id)
    except RateLimitExceeded:
        return {"openers": [], "meta": {"limited": True}}
    my_profile = db.query(Profile).filter(Profile.user_id == current_user.id).first()
    other_profile = db.query(Profile).filter(Profile.user_id == target_user_id).first()
    if not other_profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    plan = SubscriptionService().get_active_plan(db, current_user.id)
    allow_extra_styles = plan == "premium_plus"
    requested_style = (req.style or "").strip() or "default"
    style = requested_style if (requested_style == "default" or allow_extra_styles) else "default"
    allow_edgy_mode = bool(req.allow_edgy_mode) and allow_extra_styles
    conversation_context = req.conversation_context or []
    language_hint = (req.language_hint or "").strip() or None
    from app.services.app_language import resolve_ai_request_locale

    locale = resolve_ai_request_locale(req.locale or language_hint)
    premium = has_premium_access(db, current_user.id, "unlimited_ai_suggestions")
    track_event(
        db,
        "ai_chat_openers_requested",
        user_id=current_user.id,
        payload={
            "target_user_id": target_user_id,
            "thread_len": len(conversation_context) if isinstance(conversation_context, list) else None,
            "style": style,
            "language_hint": language_hint,
            "premium": premium,
        },
    )
    from app.services.ai.orchestrator import AIOrchestrator

    openers = await AIOrchestrator.generate_openers(
        me_profile=my_profile,
        target_profile=other_profile,
        allow_edgy_mode=allow_edgy_mode,
        locale=locale,
    )
    opener_texts: list[str] = []
    for row in openers or []:
        if isinstance(row, dict):
            opener_texts.append(str(row.get("text") or "").strip())
        else:
            opener_texts.append(str(row or "").strip())
    safe = filter_chat_suggestions(kind="openers", candidates=opener_texts, partner_name=getattr(other_profile, "display_name", None))
    return {
        "openers": [{"text": x.text, "style": style, "safety_flags": x.flags} for x in safe[:3]],
        "meta": {"limited": False, "style_downgraded": requested_style != style, "plan": plan},
    }


@router.post("/replies")
async def wingman_replies(
    req: GenerateRepliesRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not settings.ENABLE_AI_SUGGESTIONS:
        return {"replies": []}
    try:
        enforce_ai_limits(db, current_user.id)
    except RateLimitExceeded:
        return {"replies": []}
    # Premium gating can be applied later; keep MVP accessible for now.
    replies = await generate_replies(
        req.last_message,
        req.conversation_context,
        req.user_style,
        allow_edgy_mode=req.allow_edgy_mode,
        locale=req.locale,
    )
    return {"replies": replies}


def _profile_context(p: Profile | None) -> dict:
    if not p:
        return {}
    return {
        "display_name": _sanitize(getattr(p, "display_name", "") or "", 80),
        "bio": _sanitize(getattr(p, "bio", "") or "", 600),
        "city": _sanitize(getattr(p, "city", "") or "", 80),
        "relationship_goal": _sanitize(getattr(p, "relationship_goal", "") or "", 32),
        "interests": [x.strip() for x in (getattr(p, "interests", "") or "").split(",") if x.strip()][:10],
        "lifestyle_tags": [x.strip() for x in (getattr(p, "lifestyle_tags", "") or "").split(",") if x.strip()][:10],
        "photo_urls": [
            normalize_photo_url(x.strip(), demo_profile_gender=getattr(p, "gender", None))
            for x in (getattr(p, "photo_urls", "") or "").split(",")
            if x.strip()
        ][:6],
    }


def _format_chat_context(messages: list[dict], *, max_messages: int) -> list[dict]:
    # messages: {"role": "me"|"them", "text": "..."}
    out: list[dict] = []
    for m in (messages or [])[-max_messages:]:
        role = str(m.get("role") or "").strip().lower()
        role = "me" if role == "me" else "them"
        text = _sanitize(str(m.get("text") or ""), 900)
        if not text:
            continue
        out.append({"role": role, "text": text})
    return out[-max_messages:]


def _meeting_readiness_heuristic(chat: list[dict], *, is_premium: bool) -> int:
    # Simple heuristic: longer back-and-forth => higher readiness, but cap in free.
    n = len(chat)
    score = min(100, max(0, int(n * (2 if is_premium else 1))))
    # If both sides spoke recently (at least 2 from each), bump.
    me = sum(1 for m in chat if m.get("role") == "me")
    them = sum(1 for m in chat if m.get("role") == "them")
    if me >= 2 and them >= 2:
        score = min(100, score + 10)
    return score


def _interest_stage_from_chat(chat: list[dict]) -> dict:
    # Uses role-aware signals for mutuality.
    tail = [{"role": m.get("role"), "text": str(m.get("text") or "").strip()} for m in (chat or [])[-20:]]
    tail = [m for m in tail if m.get("text")]
    if not tail:
        return {"interest_score": 0, "stage": "cold", "mutuality_score": 0, "signals": ["no context"]}

    def _qcount(role: str) -> int:
        return sum(1 for m in tail if m.get("role") == role and "?" in (m.get("text") or ""))

    def _avg_len(role: str) -> float:
        xs = [len(str(m.get("text") or "")) for m in tail if m.get("role") == role]
        return float(sum(xs)) / float(len(xs)) if xs else 0.0

    q_me = _qcount("me")
    q_them = _qcount("them")
    avg_me = _avg_len("me")
    avg_them = _avg_len("them")

    joined = " ".join([m["text"] for m in tail]).lower()
    okish = sum(1 for token in ["ок", "окей", "норм", "ага", "мм", "ясно"] if token in joined)
    positive = sum(1 for token in ["круто", "клас", "супер", "😊", "🙂", "😉", "😄", "😂", "❤️"] if token in joined)

    both_ask = 1 if (q_me >= 1 and q_them >= 1) else 0
    only_one_asks = 1 if ((q_me >= 2 and q_them == 0) or (q_them >= 2 and q_me == 0)) else 0
    both_expand = 1 if (avg_me >= 35 and avg_them >= 35) else 0

    mutuality = 25 + 22 * both_ask + 18 * both_expand + min(20, 7 * min(q_me, q_them)) + min(15, 5 * positive) - min(25, 8 * okish) - 15 * only_one_asks
    mutuality = max(0, min(100, int(mutuality)))

    interest = 30 + min(25, 6 * (q_me + q_them)) + min(20, 5 * positive) + (10 if both_expand else 0) - min(25, 9 * okish)
    interest = max(0, min(100, int(interest)))

    stage = "cold"
    if interest >= 80 and mutuality >= 70:
        stage = "ready"
    elif interest >= 60 and mutuality >= 50:
        stage = "engaged"
    elif interest >= 40:
        stage = "warming"

    signals: list[str] = []
    if both_ask:
        signals.append("both ask questions")
    elif only_one_asks:
        signals.append("only one side asks")
    if both_expand:
        signals.append("both expand answers")
    if okish:
        signals.append("короткі відповіді")
    if positive:
        signals.append("positive эмоції")
    if not signals:
        signals.append("neutral tone")

    return {"interest_score": interest, "stage": stage, "mutuality_score": mutuality, "signals": signals[:10]}


def _meeting_suggestion_from_stage_mutuality(*, stage: str, mutuality_score: int, locale: str = "en") -> str | None:
    """
    Meeting suggestion gating rules:
    - Only when stage == "ready"
    - mutuality < 60: none
    - 60–75: soft hint
    - 75+: natural suggestion
    """
    st = (stage or "").strip().lower()
    m = int(mutuality_score or 0)
    if st != "ready":
        return None
    if m < 60:
        return None
    loc = normalize_ai_request_locale(locale or "en")
    if loc == "uk":
        if m < 75:
            return "Якщо буде комфортно, можемо якось на каву або коротку прогулянку в публічному місці — без поспіху 🙂 Як тобі такий формат?"
        return "Мені з тобою реально легко спілкуватися 🙂 Якщо тобі ок, можемо якось випити кави або прогулятися в публічному місці — як тобі така ідея?"
    if loc == "ru":
        if m < 75:
            return "Если тебе комфортно, можем как-нибудь сходить на кофе или короткую прогулку в людном месте — без спешки 🙂 Как тебе такой формат?"
        return "С тобой правда легко общаться 🙂 Если тебе ок, можем как-нибудь выпить кофе или прогуляться в людном месте — как тебе такая идея?"
    if m < 75:
        return "If it feels comfortable, we could do a coffee or a short walk in a public place sometime - no pressure 🙂 How does that sound?"
    return "I really enjoy talking with you 🙂 If you're up for it, we could grab coffee or take a short walk in a public place - how does that sound?"


def _smart_meeting_engine(
    *,
    chat: list[dict],
    locale: str,
    health_score: int | None = None,
    attraction_level: str | None = None,
    drop_risk: str | None = None,
    city: str | None = None,
    interests: list[str] | None = None,
) -> dict:
    c = [m for m in (chat or []) if str(m.get("text") or "").strip()]
    last_20 = c[-20:]
    me = [m for m in last_20 if m.get("role") == "me"]
    them = [m for m in last_20 if m.get("role") == "them"]
    exchanges = min(len(me), len(them))
    asks = sum(1 for m in them if "?" in str(m.get("text") or ""))
    short = sum(1 for m in them[-4:] if len(str(m.get("text") or "").strip()) <= 12)
    emoji = sum(1 for m in them if re.search(r"[😀-🙏❤️🥺😉😄😂😍😢😭]", str(m.get("text") or "")))
    avg_len_them = (sum(len(str(m.get("text") or "")) for m in them) / len(them)) if them else 0.0
    fast_flow = 1 if len(last_20) >= 8 and exchanges >= 4 else 0
    flirt_sig = sum(1 for m in last_20 if re.search(r"(😉|😏|❤️|ти\\s+цікав|you seem fun|з тобою)", str(m.get("text") or "").lower()))
    shared_topic = 1 if interests and len([x for x in interests if str(x or "").strip()]) >= 1 else 0

    score = 35
    score += min(15, asks * 5)
    score += 8 if emoji > 0 else 0
    score += 12 if fast_flow else 0
    score += 8 if avg_len_them >= 26 else 0
    score += 10 if flirt_sig > 0 else 0
    score += 6 if shared_topic else 0
    score -= 16 if short >= 2 else 0
    score -= 12 if asks == 0 else 0
    if health_score is not None:
        score = int(round((score * 0.65) + (int(health_score) * 0.35)))
    if attraction_level == "high":
        score += 6
    elif attraction_level == "low":
        score -= 6
    score = max(0, min(100, score))

    # hard protections
    unanswered = bool(last_20 and str(last_20[-1].get("role") or "") == "me")
    if drop_risk == "high" or (health_score is not None and int(health_score) < 50) or unanswered or exchanges < 3:
        return {
            "should_suggest": False,
            "confidence": max(15, min(55, score)),
            "type": "soft",
            "message": "",
            "reason": "Conversation is not ready for a meeting suggestion yet.",
            "meeting_readiness": score,
            "best_moment": None,
        }

    loc = normalize_ai_request_locale(locale)
    typ = "soft" if score < 70 else "light" if score < 85 else "direct"
    if typ == "soft":
        msg = (
            "з тобою це звучить як розмова для кави 🙂"
            if loc == "uk"
            else "с тобой это звучит как разговор для кофе 🙂"
            if loc == "ru"
            else "this sounds like a coffee conversation with you 🙂"
        )
    elif typ == "light":
        msg = (
            "можемо якось продовжити це за кавою? 🙂"
            if loc == "uk"
            else "можем как-нибудь продолжить это за кофе? 🙂"
            if loc == "ru"
            else "we could continue this over coffee sometime 🙂"
        )
    else:
        msg = (
            "як ти дивишся на каву в суботу?"
            if loc == "uk"
            else "как ты смотришь на кофе в субботу?"
            if loc == "ru"
            else "how about coffee this Saturday?"
        )
    if shared_topic and interests:
        top = str(interests[0]).strip().lower()
        if "спорт" in top or "run" in top:
            msg = "можна якось навіть на пробіжку вирватись 😄" if loc == "uk" else ("можно даже выбраться на пробежку 😄" if loc == "ru" else "we could even go for a run 😄")
    if city and typ in {"light", "direct"}:
        msg = f"{msg} ({city.strip()})"

    conf = max(40, min(96, score))
    return {
        "should_suggest": True,
        "confidence": conf,
        "type": typ,
        "message": _ensure_question_short(msg),
        "reason": "Strong mutual engagement, healthy flow, and good timing for a low-pressure invite.",
        "meeting_readiness": score,
        "best_moment": "evening/weekend" if conf >= 75 else None,
    }


def _chat_copilot_provider_failure_dict(
    *,
    stall: dict,
    goal_metrics_cp,
    tier_plan_cp: str,
    is_premium: bool,
    chat: list,
    copilot_locale: str,
    partner_profile,
    fallback_options: list[dict],
    trigger_reason: str,
    error_message: str,
) -> dict:
    log_ai_fallback_triggered(
        endpoint="chat-copilot",
        locale=copilot_locale,
        reason=trigger_reason,
        error_message=(error_message or "")[:2000],
        provider="gemini",
    )
    stage_meta = _interest_stage_from_chat(chat)
    health = _conversation_health_heuristic(messages=chat[-20:], locale=copilot_locale)
    meeting_engine = _smart_meeting_engine(
        chat=chat[-20:],
        locale=copilot_locale,
        health_score=int(health.get("health_score") or 50),
        attraction_level=str(health.get("attraction_level") or "medium"),
        drop_risk=str(health.get("drop_risk") or "medium"),
        city=getattr(partner_profile, "city", None),
        interests=(getattr(partner_profile, "interests", "") or "").split(",") if partner_profile else [],
    )
    meeting_readiness = int(meeting_engine.get("meeting_readiness") or 0) if is_premium else None
    meeting_suggestion = str(meeting_engine.get("message") or "") if (is_premium and bool(meeting_engine.get("should_suggest"))) else None
    if (not is_premium) and bool(meeting_engine.get("should_suggest")) and random.random() < 0.2:
        meeting_suggestion = str(meeting_engine.get("message") or "")
    best_idx = _best_index_for_stage(str(stage_meta.get("stage") or ""), int(stage_meta.get("mutuality_score") or 0))
    gm = dict(goal_metrics_cp or {}) if isinstance(goal_metrics_cp, dict) else {}
    if tier_plan_cp == "premium_plus":
        gm["meeting_engine"] = {
            "best_moment": meeting_engine.get("best_moment"),
            "confidence": int(meeting_engine.get("confidence") or 0),
            "reason": str(meeting_engine.get("reason") or "")[:180],
            "type": str(meeting_engine.get("type") or "soft"),
        }
    return {
        "strategy": None,
        "meeting_readiness": meeting_readiness if is_premium else None,
        "meeting_suggestion": meeting_suggestion,
        "best_option_index": int(best_idx),
        "options": _attach_structured_to_copilot_options(fallback_options),
        "safety_notes": [],
        "limited": False,
        "stall": stall,
        "goal_metrics": gm or goal_metrics_cp,
        "source": "fallback_engine",
        "fallback": True,
    }


def _finalize_chat_copilot_response(
    payload: dict,
    *,
    copilot_locale: str,
    last_message: str,
    continue_mode: bool,
    fallback_rows: list[dict],
    cache_hit: bool = False,
) -> dict:
    opts = payload.get("options") or []
    ok = (
        isinstance(opts, list)
        and len(opts) >= 3
        and all(str((o or {}).get("text") or "").strip() for o in opts[:3])
    )
    if ok:
        out = dict(payload)
        out.setdefault("fallback", False)
        try:
            from app.services.ai.output_script_locale import sniff_dominant_script_for_log

            joined_cp = " ".join(str((o or {}).get("text") or "") for o in (opts or [])[:3])
            log_ai_response_debug(
                route="POST /ai/chat-copilot",
                resolved_locale=copilot_locale,
                fallback_used=bool(out.get("fallback")),
                cache_hit=cache_hit,
                output_language_guess=sniff_dominant_script_for_log(joined_cp),
            )
        except Exception:
            pass
        return out
    from app.services.ai.ai_fallback_engine import copilot_suggestion_rows

    spare = copilot_suggestion_rows(copilot_locale, last_message=last_message, continue_mode=continue_mode)
    repaired: list[dict] = []
    for i in range(3):
        row = spare[i] if i < len(spare) else {}
        repaired.append(
            {
                "label": str((row or {}).get("label") or ""),
                "style": str((row or {}).get("style") or "light"),
                "text": _ensure_question_short(str((row or {}).get("text") or "")),
            }
        )
    log_ai_fallback_triggered(
        endpoint="chat-copilot",
        locale=copilot_locale,
        reason="invalid_payload_contract",
        error_message="options_invalid_or_short",
        provider="gemini",
    )
    merged = {
        **payload,
        "options": _attach_structured_to_copilot_options(repaired),
        "fallback": True,
        "source": "fallback_engine",
    }
    try:
        from app.services.ai.output_script_locale import sniff_dominant_script_for_log

        joined_cp = " ".join(str((o or {}).get("text") or "") for o in (repaired or [])[:3])
        log_ai_response_debug(
            route="POST /ai/chat-copilot",
            resolved_locale=copilot_locale,
            fallback_used=True,
            cache_hit=cache_hit,
            output_language_guess=sniff_dominant_script_for_log(joined_cp),
        )
    except Exception:
        pass
    return merged


@router.post("/chat-copilot", response_model=ChatCopilotResponse)
async def chat_copilot(
    req: ChatCopilotRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    partner_user_id = int(req.partner_user_id)
    if is_blocked(db, current_user.id, partner_user_id):
        raise HTTPException(status_code=403, detail=api_error("chat.user_blocked"))
    if not users_are_matched(db, current_user.id, partner_user_id):
        raise HTTPException(status_code=403, detail=api_error("chat.match_required"))

    plan = SubscriptionService().get_active_plan(db, current_user.id)
    is_premium = plan in {"premium", "premium_plus"}
    tier = "premium" if is_premium else "free"
    max_msgs = 50 if is_premium else 15

    # IMPORTANT: do not start trial on open. Trial starts on (a) AI suggestion click, or (b) 3+ messages.

    rows = (
        db.query(Message)
        .filter(
            ((Message.sender_id == current_user.id) & (Message.receiver_id == partner_user_id))
            | ((Message.sender_id == partner_user_id) & (Message.receiver_id == current_user.id))
        )
        .order_by(Message.created_at.desc())
        .limit(max_msgs)
        .all()
    )
    rows.reverse()
    chat: list[dict] = []
    for m in rows:
        role = "me" if int(m.sender_id) == int(current_user.id) else "them"
        text = (m.content or "").strip()
        if not text and getattr(m, "voice_url", None):
            text = "[voice message]"
        if not text:
            continue
        chat.append({"role": role, "text": text})
    chat = _format_chat_context(chat, max_messages=max_msgs)

    # Stall detection (used to switch from normal copilot to revive/re-engage).
    hours_since_last: float | None = None
    try:
        if rows:
            last_dt = getattr(rows[-1], "created_at", None)
            if last_dt is not None:
                from datetime import datetime, UTC

                now = datetime.now(UTC)
                dt = last_dt if getattr(last_dt, "tzinfo", None) else last_dt.replace(tzinfo=UTC)
                hours_since_last = max(0.0, float((now - dt).total_seconds()) / 3600.0)
    except Exception:
        hours_since_last = None

    stall: dict = {"is_stalled": False, "stall_score": 0, "reasons": []}
    try:
        if settings.ENABLE_AI_SUGGESTIONS and settings.AI_PROVIDER == "gemini" and (settings.GEMINI_API_KEY or "").strip():
            client0 = GeminiClient()
            stall_system = (
                "You are NEYRA AI.\n"
                "Detect if conversation is stalling.\n"
                "Return STRICT JSON:\n"
                '{ "is_stalled": true/false, "stall_score": 0-100, "reasons": ["short replies","no questions","long pause"] }\n'
                "Rules:\n"
                "- High stall_score if last 3 replies are short, no questions, tone is neutral/cold.\n"
                "Do not add extra keys."
            )
            stall_payload = {"messages": [x.get("text", "") for x in chat[-30:]], "hours_since_last_message": hours_since_last}
            stall = await client0.generate_json(system_prompt=stall_system, user_prompt=f"INPUT_JSON:\n{stall_payload}", temperature=0.2, max_output_tokens=160)
            # sanitize
            stall = stall if isinstance(stall, dict) else {}
            is_stalled = bool(stall.get("is_stalled"))
            try:
                score = int(stall.get("stall_score"))
            except Exception:
                score = 0
            reasons_raw = stall.get("reasons") if isinstance(stall.get("reasons"), list) else []
            reasons = [str(r or "").strip() for r in reasons_raw if str(r or "").strip()][:6]
            stall = {"is_stalled": is_stalled, "stall_score": max(0, min(100, score)), "reasons": reasons}
        else:
            stall = _detect_stall_fallback(chat, hours_since_last=hours_since_last)
    except Exception:
        stall = _detect_stall_fallback(chat, hours_since_last=hours_since_last)

    from app.services.ai.conversation_goal_engine import (
        compute_conversation_goal_state as _compute_goal_cp,
        goal_state_prompt_block as _goal_prompt_cp,
        premium_plus_goal_metrics_public as _goal_metrics_pp,
    )

    latest_user_message = next((str(x.get("text") or "").strip() for x in reversed(chat) if str(x.get("role") or "") == "me" and str(x.get("text") or "").strip()), "")
    copilot_locale = _resolve_ai_locale_for_request(
        req_locale=getattr(req, "locale", None),
        ai_locale=getattr(req, "ai_locale", None),
        request=request,
        db=db,
        current_user=current_user,
        latest_user_message=latest_user_message,
        prefer_message_locale=False,
        route_label="POST /ai/chat-copilot",
    )
    logger.info("AI locale used: %s", copilot_locale)
    _loc_goal_cp = copilot_locale
    tier_plan_cp = plan if plan in {"free", "premium", "premium_plus"} else "free"
    _who_lc = chat[-1].get("role") if chat else None
    _who_lc = _who_lc if _who_lc in {"me", "them"} else None
    _stage_cp = _interest_stage_from_chat(chat)
    goal_state_cp = _compute_goal_cp(
        chat,
        plan_tier=tier_plan_cp,
        locale=_loc_goal_cp,
        hours_since_last_message=hours_since_last,
        who_sent_last=_who_lc,
        interest_stage=str(_stage_cp.get("stage") or ""),
        mutuality_score=int(_stage_cp.get("mutuality_score") or 0),
    )
    goal_cp_prompt = _goal_prompt_cp(goal_state_cp) if is_premium else ""
    goal_metrics_cp = _goal_metrics_pp(goal_state_cp, locale=_loc_goal_cp) if tier_plan_cp == "premium_plus" else None

    my_profile = db.query(Profile).filter(Profile.user_id == current_user.id).first()
    partner_profile = db.query(Profile).filter(Profile.user_id == partner_user_id).first()
    ai_prof = db.query(UserAiProfile).filter(UserAiProfile.user_id == current_user.id).first()

    logger.info(
        "ai_copilot_requested",
        extra={
            "tier": tier,
            "context_messages_count": len(chat),
            "provider": settings.AI_PROVIDER,
            "partner_user_id": partner_user_id,
        },
    )
    track_event(
        db,
        "ai_copilot_requested",
        user_id=current_user.id,
        payload={"tier": tier, "context_messages_count": len(chat), "partner_user_id": partner_user_id},
    )

    log_ai_locale_context(
        logger,
        endpoint="chat-copilot",
        ui_locale=getattr(req, "locale", None),
        ai_locale=copilot_locale,
    )

    _closer_stage_cp, _ = compute_closer_stage(
        chat,
        stalled_chat=bool((stall or {}).get("is_stalled")),
    )

    # Fallback options (always available, fast).
    last_message = ""
    for m in reversed(chat):
        if m.get("role") == "them":
            last_message = str(m.get("text") or "")
            break
    if not last_message and chat:
        last_message = str(chat[-1].get("text") or "")
    # Stage-aware mode: avoid repeating openers once the convo has started.
    mode = "opener"
    if len(chat) >= 2:
        mode = "continue"
    if chat and str(chat[-1].get("role") or "") == "them":
        mode = "reply"
    fb3 = await _fallback_3_replies_localized(
        last_message,
        locale=copilot_locale,
        continue_mode=mode in {"continue", "reply"},
        closer_stage=_closer_stage_cp,
    )
    lb_l, lb_f, lb_d = _copilot_fallback_labels(copilot_locale)
    fallback_options = [
        {"label": lb_l, "style": "light", "text": _ensure_question_short(fb3[0])},
        {"label": lb_f, "style": "flirty", "text": _ensure_question_short(fb3[1])},
        {"label": lb_d, "style": "deep", "text": _ensure_question_short(fb3[2])},
    ]

    # If stalled, return revive options (and keep premium extras if available).
    if bool((stall or {}).get("is_stalled")):
        revive_options = None
        if settings.ENABLE_AI_SUGGESTIONS and settings.AI_PROVIDER == "gemini" and (settings.GEMINI_API_KEY or "").strip():
            try:
                clientR = GeminiClient()
                revive_system = (
                    "You are NEYRA Copilot.\n"
                    "Goal: Revive conversation naturally.\n"
                    "Rules:\n"
                    "- 3 DISTINCT replies\n"
                    "- Each ends with a question\n"
                    "- 1–2 sentences\n"
                    f"- IMPORTANT: Answer ONLY in {copilot_locale}\n"
                    "- No cringe\n"
                    "Types:\n"
                    "1. Topic shift\n"
                    "2. Personal hook / interests\n"
                    "3. Playful\n"
                    "Output STRICT JSON:\n"
                    '{ "options": [ {"type":"topic_shift","text":"..."}, {"type":"personal_hook","text":"..."}, {"type":"playful","text":"..."} ] }\n'
                    "Do not add extra keys."
                )
                revive_payload = {"messages": [x.get("text", "") for x in chat[-30:]]}
                out = await clientR.generate_json(system_prompt=revive_system, user_prompt=f"INPUT_JSON:\n{revive_payload}", temperature=0.65, max_output_tokens=320)
                rows0 = out.get("options") if isinstance(out, dict) else None
                if isinstance(rows0, list):
                    mapped: list[dict] = []
                    for r in rows0[:3]:
                        if not isinstance(r, dict):
                            continue
                        t = str(r.get("type") or "").strip()
                        text = _ensure_question_short(str(r.get("text") or "").strip())
                        if not text:
                            continue
                        if t == "topic_shift":
                            mapped.append({"label": "Topic shift", "style": "light", "text": text})
                        elif t == "personal_hook":
                            mapped.append({"label": "Personal hook", "style": "deep", "text": text})
                        else:
                            mapped.append({"label": "Playful", "style": "flirty", "text": text})
                    if len(mapped) == 3:
                        revive_options = mapped
            except Exception:
                revive_options = None
        if not revive_options:
            revive_options = _revive_fallback(chat, locale=copilot_locale)

        stage_meta = _interest_stage_from_chat(chat)
        health = _conversation_health_heuristic(messages=chat[-20:], locale=copilot_locale)
        meeting_engine = _smart_meeting_engine(
            chat=chat[-20:],
            locale=copilot_locale,
            health_score=int(health.get("health_score") or 50),
            attraction_level=str(health.get("attraction_level") or "medium"),
            drop_risk=str(health.get("drop_risk") or "medium"),
            city=getattr(partner_profile, "city", None),
            interests=(getattr(partner_profile, "interests", "") or "").split(",") if partner_profile else [],
        )
        meeting_readiness = int(meeting_engine.get("meeting_readiness") or 0) if is_premium else None
        meeting_suggestion = str(meeting_engine.get("message") or "") if (is_premium and bool(meeting_engine.get("should_suggest"))) else None
        if (not is_premium) and bool(meeting_engine.get("should_suggest")) and random.random() < 0.2:
            meeting_suggestion = str(meeting_engine.get("message") or "")
        best_idx = _best_index_for_stage(str(stage_meta.get("stage") or ""), int(stage_meta.get("mutuality_score") or 0))
        gm = dict(goal_metrics_cp or {}) if isinstance(goal_metrics_cp, dict) else {}
        if tier_plan_cp == "premium_plus":
            gm["meeting_engine"] = {
                "best_moment": meeting_engine.get("best_moment"),
                "confidence": int(meeting_engine.get("confidence") or 0),
                "reason": str(meeting_engine.get("reason") or "")[:180],
                "type": str(meeting_engine.get("type") or "soft"),
            }
        return _finalize_chat_copilot_response(
            {
                "strategy": None,
                "meeting_readiness": meeting_readiness if is_premium else None,
                "meeting_suggestion": meeting_suggestion,
                "best_option_index": int(best_idx),
                "options": _attach_structured_to_copilot_options(revive_options),
                "safety_notes": [],
                "limited": False,
                "stall": stall,
                "goal_metrics": gm or goal_metrics_cp,
                "fallback": False,
                "source": "revive_local",
            },
            copilot_locale=copilot_locale,
            last_message=last_message,
            continue_mode=mode in {"continue", "reply"},
            fallback_rows=fallback_options,
        )

    # Smart paywall: when free AI quota is exhausted, return blurred options via `limited=true`.
    if not is_premium:
        try:
            enforce_ai_limits(db, current_user.id)
        except RateLimitExceeded:
            logger.info(
                "ai_paywall_shown",
                extra={"endpoint": "chat-copilot", "tier": tier, "provider": "fallback", "options_count": 3},
            )
            track_event(db, "ai_paywall_shown", user_id=current_user.id, payload={"endpoint": "chat-copilot"})
            return _finalize_chat_copilot_response(
                {
                    "strategy": None,
                    "meeting_readiness": None,
                    "meeting_suggestion": None,
                    "best_option_index": 0,
                    "options": _attach_structured_to_copilot_options(fallback_options),
                    "safety_notes": [],
                    "limited": True,
                    "stall": stall,
                    "goal_metrics": None,
                    "fallback": False,
                    "source": "paywall_limited",
                },
                copilot_locale=copilot_locale,
                last_message=last_message,
                continue_mode=mode in {"continue", "reply"},
                fallback_rows=fallback_options,
            )

    if not settings.ENABLE_AI_SUGGESTIONS or settings.AI_PROVIDER != "gemini" or not (settings.GEMINI_API_KEY or "").strip():
        return _finalize_chat_copilot_response(
            _chat_copilot_provider_failure_dict(
                stall=stall,
                goal_metrics_cp=goal_metrics_cp,
                tier_plan_cp=tier_plan_cp,
                is_premium=is_premium,
                chat=chat,
                copilot_locale=copilot_locale,
                partner_profile=partner_profile,
                fallback_options=fallback_options,
                trigger_reason="AiUnavailable",
                error_message="ai_disabled_or_missing_gemini_key",
            ),
            copilot_locale=copilot_locale,
            last_message=last_message,
            continue_mode=mode in {"continue", "reply"},
            fallback_rows=fallback_options,
        )

    # Premium context (only when eligible).
    user_ctx = _profile_context(my_profile) if is_premium else {}
    partner_ctx = _profile_context(partner_profile) if is_premium else {}
    photo_ctx_note = "If photo captions/tags exist, use them. If not, do NOT invent photo details. (Vision analysis TODO.)"

    system = (
        (
            "You are NEYRA AI Dating Copilot — help the user reply in a human, specific way (not interview templates).\n"
            "Generate EXACTLY 3 different replies for the USER to send.\n"
            "Coach goals:\n"
            "- Anchor every line in the partner's LAST message: reuse a concrete noun, plan, feeling, or joke they mentioned.\n"
            "- If they asked a question, engage with that thread first (do not deflect with generic meta-questions).\n"
            "- Keep momentum: each line invites an easy answer without sounding like a form.\n"
            "Rules:\n"
            f"You MUST respond ONLY in {copilot_locale}. Never switch language. Never use English unless locale is en.\n"
            "- Each reply: 1–2 sentences max; MUST end with one clear question.\n"
            "- Each reply must be UNIQUE in structure and angle.\n"
            "- Never invent facts not present in chat or profiles.\n"
            "- Banned shallow fillers (Ukrainian examples — never use): «що ти думаєш», «що маєш на увазі», «розкажи більше» as a standalone dodge.\n"
            "Style mapping (JSON keys are fixed for the API):\n"
            "- key `light` → WARM: kind, grounded, specific to their words.\n"
            "- key `flirty` → FLIRTY: romantic tension, playful confidence, still respectful.\n"
            "- key `deep` → PLAYFUL: witty / lively / curious — NOT heavy therapy; stay light on your feet.\n"
        )
        + closer_copilot_prompt_addon(_closer_stage_cp, copilot_locale)
        + (("\n" + goal_cp_prompt) if goal_cp_prompt else "")
    )

    learned_style = (ai_prof.preferred_style if ai_prof else "") or ""
    emoji_level = float(ai_prof.emoji_usage_level) if ai_prof else 0.0
    avg_len = float(ai_prof.avg_message_length) if ai_prof else 0.0
    length_bucket = "short" if avg_len and avg_len < 70 else "medium" if avg_len and avg_len < 140 else "long" if avg_len else "medium"
    user_style_ctx = {
        "preferred": learned_style or None,
        "emoji_level": max(0.0, min(1.0, emoji_level)),
        "message_length": length_bucket,
        "edit_rate": float(ai_prof.edit_rate) if ai_prof else 0.0,
    }

    mem_ctx = build_memory_context_for_prompt(db, user_id=current_user.id, partner_user_id=partner_user_id) if is_premium else {}
    recent_questions = _recent_question_texts(chat, limit=6)
    partner_signals = build_last_message_reply_context(str(last_message or ""))
    user = {
        "tier": tier,
        "mode": mode,
        "chat": chat,
        "last_partner_message": str(last_message or "").strip(),
        "partner_message_tone": partner_signals.get("tone"),
        "partner_message_intent": partner_signals.get("intent"),
        "reply_guidance": partner_signals.get("guidance_for_replies"),
        "last_message_excerpt": partner_signals.get("last_message_excerpt"),
        "recent_questions": recent_questions,
        "user_profile": user_ctx,
        "partner_profile": partner_ctx,
        "user_style": user_style_ctx,
        "memory": mem_ctx.get("AI_MEMORY") if isinstance(mem_ctx, dict) else {},
        "notes": photo_ctx_note,
    }
    user_prompt = (
        f"INPUT_JSON:\n{user}\n\n"
        "Use `partner_message_tone`, `partner_message_intent`, and `reply_guidance` to match how they wrote.\n"
        "Return JSON with keys: strategy, meeting_readiness (0-100 or null), "
        "meeting_suggestion (string or null), options[3] with labels ['Warm','Flirty','Playful'], safety_notes[]."
    )

    client = GeminiClient()
    _cp_to = 1.5 if tier == "free" else 1.8

    regen_triggered = False
    try:
        # HARD logging for Gemini usage (before any fallback).
        try:
            approx_input_size = len(system) + len(user_prompt) + 240  # small cushion for persona/avoid text
            logger.info(json.dumps({"event": "gemini_attempt", "endpoint": "chat-copilot", "input_size": int(approx_input_size)}, default=str))
        except Exception:
            pass

        # Single Gemini round-trip (3 styles in one JSON) — matches one-upstream-POST policy per request.
        system_triple = (
            system
            + "\n\nOUTPUT: Return ONLY JSON: {\"light\":\"...\",\"flirty\":\"...\",\"deep\":\"...\"}.\n"
            "Keys map to: light=WARM, flirty=FLIRTY, deep=PLAYFUL (witty/lively — not heavy 'deep talk').\n"
            "Each value must reference something concrete from last_partner_message; "
            "1–2 sentences; MUST end with ?; three clearly different ideas.\n"
        )
        triple = await client.generate_json(
            system_prompt=system_triple,
            user_prompt=user_prompt
            + '\n\nReturn JSON only, keys light, flirty, deep — no other top-level keys. Example: {"light":"...","flirty":"...","deep":"..."}',
            out_model=CopilotTripleLineOut,
            timeout_s=_cp_to,
            temperature=0.72,
            surface="chat-copilot",
            model=settings.GEMINI_CHAT_MODEL,
        )
        light = _ensure_question_short(str(triple.light or ""))
        flirty = _ensure_question_short(str(triple.flirty or ""))
        deep = _ensure_question_short(str(triple.deep or ""))
        if normalize_ai_request_locale(copilot_locale) == "uk":
            light = _scrub_banned_uk_reply_phrases(light)
            flirty = _scrub_banned_uk_reply_phrases(flirty)
            deep = _scrub_banned_uk_reply_phrases(deep)

        # Hard validation (single pass): no Gemini regen loops — use deterministic fallback if QA fails.
        threshold = 0.60
        texts = [light, flirty, deep]
        sim_lf = _pair_similarity(light, flirty)
        sim_ld = _pair_similarity(light, deep)
        sim_fd = _pair_similarity(flirty, deep)
        max_sim = max(sim_lf, sim_ld, sim_fd)

        english_flags = [_has_english(t) for t in texts]
        same_q = _same_question(light, flirty) or _same_question(light, deep) or _same_question(flirty, deep)
        if mode in {"continue", "reply"} and recent_questions:
            for q in recent_questions[:6]:
                if _same_question(light, q) or _same_question(flirty, q) or _same_question(deep, q):
                    same_q = True
                    break

        overlap_flags = [
            _overlap_ratio(last_message, light) > 0.40,
            _overlap_ratio(last_message, flirty) > 0.40,
            _overlap_ratio(last_message, deep) > 0.40,
        ]

        sigs = [_structure_sig(light), _structure_sig(flirty), _structure_sig(deep)]
        same_structure = (sigs[0] and sigs[0] == sigs[1]) or (sigs[0] and sigs[0] == sigs[2]) or (sigs[1] and sigs[1] == sigs[2])
        kw_sim = max(_keyword_jaccard(light, flirty), _keyword_jaccard(light, deep), _keyword_jaccard(flirty, deep))

        def _intent_ok() -> bool:
            l = _norm_for_sim(light)
            f = _norm_for_sim(flirty)
            d = _norm_for_sim(deep)
            # Warm lane: allow emoji markers or at least a question (locale-agnostic fallbacks).
            light_ok = any(x in l for x in ["🙂", "круто", "окей", "супер", "кайф", "тепл"]) or ("?" in l)
            # Flirty lane: curiosity / spark language.
            curious_ok = any(
                x in f
                for x in [
                    "якби",
                    "уяви",
                    "секрет",
                    "підозра",
                    "а раптом",
                    "перевіримо",
                    "з тобою",
                    "цікав",
                    "флірт",
                    "😉",
                ]
            ) or ("?" in f)
            # Playful lane (key `deep`): wit / energy — not the old “heavy deep” probe list only.
            playful_ok = any(
                x in d
                for x in [
                    "чому",
                    "що саме",
                    "відгукується",
                    "важливіше",
                    "відчуття",
                    "якби",
                    "уяви",
                    "раптом",
                    "прикол",
                    "сміш",
                    "лол",
                    "🙂",
                    "😉",
                ]
            ) or ("?" in d)
            return bool(light_ok and curious_ok and playful_ok)

        uk_ban_ok = True
        if normalize_ai_request_locale(copilot_locale) == "uk":
            uk_ban_ok = not any(_has_banned_uk_reply_phrase(t) for t in texts)

        validation_ok = (
            uk_ban_ok
            and (max_sim <= threshold)
            and (not any(english_flags))
            and (not same_q)
            and (not any(overlap_flags))
            and (not same_structure)
            and (kw_sim <= 0.55)
            and _intent_ok()
        )

        regen_triggered = not validation_ok
        if not validation_ok:
            fb = await _fallback_3_replies_localized(
                last_message or "",
                locale=copilot_locale,
                continue_mode=mode in {"continue", "reply"},
                closer_stage=_closer_stage_cp,
            )
            light, flirty, deep = fb[0], fb[1], fb[2]
            try:
                log_ai_provider_final(ai_provider_final="fallback", endpoint="chat-copilot", reason="validation_failed")
            except Exception:
                pass

        fixed = await _enforce_ai_texts_locale_once([light, flirty, deep], locale=copilot_locale)
        if len(fixed) == 3:
            light, flirty, deep = fixed[0], fixed[1], fixed[2]
        provider_used = "gemini"
        diversity = round(_diversity_score([light, flirty, deep]), 4)
        logger.info(
            "ai_chat_suggestions_generated",
            extra={
                "tier": tier,
                "provider": provider_used,
                "options_count": 3,
                "meeting_readiness": None,
                "diversity_score": diversity,
                "regeneration_triggered": regen_triggered,
            },
        )
        track_event(
            db,
            "ai_chat_suggestions_generated",
            user_id=current_user.id,
            payload={"tier": tier, "provider": provider_used, "options_count": 3, "diversity_score": diversity, "regeneration_triggered": regen_triggered},
        )

        # Smart meeting timing engine.
        stage_meta = _interest_stage_from_chat(chat)
        health = _conversation_health_heuristic(messages=chat[-20:], locale=copilot_locale)
        meeting_engine = _smart_meeting_engine(
            chat=chat[-20:],
            locale=copilot_locale,
            health_score=int(health.get("health_score") or 50),
            attraction_level=str(health.get("attraction_level") or "medium"),
            drop_risk=str(health.get("drop_risk") or "medium"),
            city=getattr(partner_profile, "city", None),
            interests=(getattr(partner_profile, "interests", "") or "").split(",") if partner_profile else [],
        )
        meeting_readiness = int(meeting_engine.get("meeting_readiness") or 0) if is_premium else None
        meeting_suggestion = str(meeting_engine.get("message") or "") if (is_premium and bool(meeting_engine.get("should_suggest"))) else None
        if (not is_premium) and bool(meeting_engine.get("should_suggest")) and random.random() < 0.2:
            meeting_suggestion = str(meeting_engine.get("message") or "")
        best_idx = _best_index_for_stage(str(stage_meta.get("stage") or ""), int(stage_meta.get("mutuality_score") or 0))
        gm = dict(goal_metrics_cp or {}) if isinstance(goal_metrics_cp, dict) else {}
        if tier_plan_cp == "premium_plus":
            gm["meeting_engine"] = {
                "best_moment": meeting_engine.get("best_moment"),
                "confidence": int(meeting_engine.get("confidence") or 0),
                "reason": str(meeting_engine.get("reason") or "")[:180],
                "type": str(meeting_engine.get("type") or "soft"),
            }
        try:
            logger.info(json.dumps({"event": "gemini_success", "endpoint": "chat-copilot"}, default=str))
        except Exception:
            pass
        _lb_w, _lb_f, _lb_p = _copilot_fallback_labels(copilot_locale)
        return _finalize_chat_copilot_response(
            {
                "strategy": None if not is_premium else None,
                "meeting_readiness": None if not is_premium else meeting_readiness,
                "meeting_suggestion": meeting_suggestion,
                "best_option_index": int(best_idx),
                "options": _attach_structured_to_copilot_options(
                    [
                        {"label": _lb_w, "style": "light", "text": light},
                        {"label": _lb_f, "style": "flirty", "text": flirty},
                        {"label": _lb_p, "style": "deep", "text": deep},
                    ]
                ),
                "safety_notes": [],
                "limited": False,
                "stall": stall,
                "goal_metrics": gm or goal_metrics_cp,
                "fallback": False,
                "source": "gemini",
            },
            copilot_locale=copilot_locale,
            last_message=last_message,
            continue_mode=mode in {"continue", "reply"},
            fallback_rows=fallback_options,
        )
    except GeminiError as e:
        try:
            logger.error(
                json.dumps(
                    {
                        "event": "gemini_error",
                        "endpoint": "chat-copilot",
                        "status": e.status_code,
                        "response_body": (e.response_body or "")[:4000] if e.response_body else None,
                        "exception": str(e.message or e.code),
                        "code": e.code,
                        "model": str(e.model or ""),
                    },
                    default=str,
                )
            )
        except Exception:
            pass
        logger.warning(
            "ai_request_failed",
            extra={"endpoint": "chat-copilot", "tier": tier, "provider": "gemini", "code": e.code, "regeneration_triggered": regen_triggered},
        )
        set_last_provider_used("fallback")
        set_last_gemini_error(f"{e.code}: {e.message}")
        incr_fallback_24h()
        # Production hardening: if Gemini is quota/cooldown-limited, return safe localized fallback
        # and avoid scary repeated client-side alerts/retries.
        if str(getattr(e, "code", "") or "") in {"quota_exhausted", "cooldown_active"}:
            logger.info(
                "ai_fallback_used",
                extra={"endpoint": "chat-copilot", "provider": "fallback", "reason": e.code, "status": e.status_code},
            )
            return _finalize_chat_copilot_response(
                {
                    "strategy": None,
                    "meeting_readiness": None,
                    "meeting_suggestion": None,
                    "best_option_index": 0,
                    "options": _attach_structured_to_copilot_options(fallback_options),
                    "safety_notes": [],
                    "limited": False,
                    "stall": stall,
                    "source": "fallback_quota",
                    "fallback": True,
                    "fallback_reason": str(e.code),
                    "goal_metrics": goal_metrics_cp,
                },
                copilot_locale=copilot_locale,
                last_message=last_message,
                continue_mode=mode in {"continue", "reply"},
                fallback_rows=fallback_options,
            )
        return _finalize_chat_copilot_response(
            _chat_copilot_provider_failure_dict(
                stall=stall,
                goal_metrics_cp=goal_metrics_cp,
                tier_plan_cp=tier_plan_cp,
                is_premium=is_premium,
                chat=chat,
                copilot_locale=copilot_locale,
                partner_profile=partner_profile,
                fallback_options=fallback_options,
                trigger_reason=str(getattr(e, "code", "") or "GeminiError"),
                error_message=f"{getattr(e, 'code', '')}: {getattr(e, 'message', '')}",
            ),
            copilot_locale=copilot_locale,
            last_message=last_message,
            continue_mode=mode in {"continue", "reply"},
            fallback_rows=fallback_options,
        )
    except Exception as ex:
        return _finalize_chat_copilot_response(
            _chat_copilot_provider_failure_dict(
                stall=stall,
                goal_metrics_cp=goal_metrics_cp,
                tier_plan_cp=tier_plan_cp,
                is_premium=is_premium,
                chat=chat,
                copilot_locale=copilot_locale,
                partner_profile=partner_profile,
                fallback_options=fallback_options,
                trigger_reason=type(ex).__name__,
                error_message=str(ex),
            ),
            copilot_locale=copilot_locale,
            last_message=last_message,
            continue_mode=mode in {"continue", "reply"},
            fallback_rows=fallback_options,
        )


def _ensure_question(text: str, locale: str | None) -> str:
    s = " ".join((text or "").strip().split())
    loc = normalize_ai_request_locale(locale)
    if not s:
        if loc == "ru":
            return "Класс. А что для тебя в этом самое важное?"
        if loc == "uk":
            return "Супер. А що для тебе в цьому найважливіше?"
        if loc == "zh-TW":
            return "很好。關於這點，你最在意的是什麼？"
        if loc == "zh":
            return "很好。关于这点，你最在意的是什么？"
        return "Nice. What matters most to you about that?"
    # Must end with a question.
    if not s.endswith("?"):
        s = s.rstrip(".!… ")
        s = f"{s}?"
    # 1–2 sentences, keep it short.
    parts = [p.strip() for p in s.split("?") if p.strip()]
    if len(parts) > 2:
        s = "? ".join(parts[:2]).strip() + "?"
    return s[:220]


def _analyze_reply_context(last_message: str, conversation_context: list[str]) -> dict:
    msg = str(last_message or "").strip()
    mlow = msg.lower()
    q = "?" in msg
    mlen = len(msg)
    emotional = bool(re.search(r"(love|miss|feel|sorry|hurt|afraid|anxious|❤️|🥺|😭|😢|важливо|люб|сум|болить|чувств|трев)", mlow))
    dry = mlen <= 22 and not q and not emotional
    tone = "emotional" if emotional else "dry" if dry else "short" if mlen < 40 else "neutral"
    energy = "low" if dry else "high" if emotional or "!" in msg else "mid"
    depth = max(0, min(30, len(conversation_context or [])))
    if depth <= 2:
        stage = "ice"
    elif depth <= 8:
        stage = "connection"
    elif depth <= 18:
        stage = "comfort"
    else:
        stage = "ready"
    return {
        "question": q,
        "length": mlen,
        "tone": tone,
        "energy": energy,
        "stage": stage,
        "dry": dry,
        "emotional": emotional,
    }


def _reply_score(text: str, *, analysis: dict, stage: str) -> int:
    s = str(text or "").strip()
    if not s:
        return 0
    score = 45
    if "?" in s:
        score += 20
    if len(s) <= 220:
        score += 8
    if analysis.get("question") and ("?" in s):
        score += 8
    if analysis.get("dry") and len(s) > 30:
        score += 5
    if analysis.get("emotional") and re.search(r"(розум|відчува|цін|понима|чувств|feel|get it|hear you)", s.lower()):
        score += 8
    if stage == "ready" and re.search(r"(кав|офлайн|вживу|coffee|offline|встрет)", s.lower()):
        score += 10
    if re.search(r"(мені здається вживу це ще краще зайде|з тобою це звучить цікавіше)", s.lower()):
        score += 6
    return max(0, min(100, score))


def _best_reply_payload(*, options: list[str], analysis: dict, locale: str) -> dict:
    stage = str(analysis.get("stage") or "connection")
    rows = [{"text": x, "score": _reply_score(x, analysis=analysis, stage=stage)} for x in (options or []) if str(x or "").strip()]
    if not rows:
        return {
            "best_reply": "",
            "alternatives": [],
            "why_best": "Simple, personal, and easy to reply - keeps conversation going.",
            "confidence": 0,
            "stage": stage,
        }
    rows.sort(key=lambda r: int(r["score"]), reverse=True)
    best = str(rows[0]["text"])
    alts = [{"text": str(r["text"]), "type": ("playful" if i == 0 else "deep")} for i, r in enumerate(rows[1:3])]
    return {
        "best_reply": best,
        "alternatives": alts,
        "why_best": "Simple, personal, and easy to reply - keeps conversation going.",
        "confidence": int(rows[0]["score"]),
        "stage": stage,
    }


def _conversation_health_heuristic(*, messages: list[dict], locale: str) -> dict:
    rows = [{"role": str(m.get("role") or ""), "text": str(m.get("text") or "").strip()} for m in (messages or []) if str(m.get("text") or "").strip()]
    tail = rows[-10:]
    if not tail:
        return {
            "health_score": 50,
            "attraction_level": "medium",
            "drop_risk": "medium",
            "trend": "stable",
            "signals": ["limited signals"],
            "diagnosis": "Not enough context yet.",
            "next_move": "Ask one light personal question and keep it short.",
            "next_suggestions": fallback_reply_triplet(locale=locale)[:3],
        }
    score = 50
    signals: list[str] = []
    their = [x for x in tail if x["role"] in {"them", "partner"}]
    short_replies = sum(1 for x in their[-3:] if len(x["text"]) <= 14)
    asks_questions = sum(1 for x in their if "?" in x["text"])
    if asks_questions > 0:
        score += 15
        signals.append("she asks questions")
    if short_replies >= 2:
        score -= 20
        signals.append("short replies")
    emoji_cnt = sum(1 for x in their if re.search(r"[😀-🙏❤️🥺😉😄😂😍😢😭]", x["text"]))
    if emoji_cnt > 0:
        score += 10
        signals.append("emoji warmth")
    no_q = asks_questions == 0
    if no_q:
        score -= 10
        signals.append("no questions")
    # crude delay proxy from role turns: repeated "me" without "them"
    no_reply_window = False
    if len(tail) >= 3 and all(x["role"] == "me" for x in tail[-2:]):
        score -= 15
        no_reply_window = True
        signals.append("long delay / no reply")

    # trend by last 3 vs previous 3 message energy
    def _energy(chunk: list[dict]) -> int:
        e = 0
        for x in chunk:
            t = x["text"]
            if "?" in t:
                e += 2
            if re.search(r"[!😀-🙏❤️😉😄😂😍]", t):
                e += 2
            if len(t) > 24:
                e += 1
            if len(t) <= 8:
                e -= 1
        return e

    prev = tail[-6:-3] if len(tail) >= 6 else tail[:-3]
    last = tail[-3:]
    trend = "stable"
    if _energy(last) > _energy(prev) + 1:
        trend = "improving"
    elif _energy(last) + 1 < _energy(prev):
        trend = "declining"

    score = max(0, min(100, score))
    attraction = "high" if score >= 72 else "medium" if score >= 45 else "low"
    high_drop = bool(no_reply_window or (short_replies >= 2 and no_q and trend == "declining"))
    drop_risk = "high" if high_drop else "medium" if score < 50 or trend == "declining" else "low"
    stage = "ready" if score >= 72 else "comfort" if score >= 60 else "connection" if score >= 40 else "ice"
    if stage == "ready":
        next_move = "It's a good moment to suggest meeting."
    elif drop_risk == "high":
        next_move = "Change topic - current one is dying."
    elif attraction == "medium":
        next_move = "Add energy and ask something personal."
    else:
        next_move = "Keep it light and ask one easy question."

    diag = "🔥 Good vibe" if score >= 70 else "⚠️ You're losing her" if drop_risk == "high" else "💡 Try this: keep momentum with one personal hook."
    return {
        "health_score": score,
        "attraction_level": attraction,
        "drop_risk": drop_risk,
        "trend": trend,
        "signals": signals[:10] or ["neutral tone"],
        "diagnosis": diag,
        "next_move": next_move,
        "next_suggestions": fallback_reply_triplet(locale=locale)[:3],
        "stage": stage,
    }


@router.post("/reply-options", response_model=ReplyOptionsResponse)
async def reply_options(
    req: ReplyOptionsRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Real-time 3-option reply suggestions for chat threads.

    Returns exactly 3 short options (question-ending), with fast fallback.
    """
    raw_ui = getattr(req, "locale", None)
    locale = normalize_ai_request_locale(raw_ui or "en")
    log_ai_locale_context(logger, endpoint="reply-options", ui_locale=raw_ui, ai_locale=locale)
    req.locale = locale

    # Keep this endpoint snappy: no paywall gating, but still rate-limited.
    try:
        enforce_ai_limits(db, current_user.id)
    except RateLimitExceeded:
        logger.info("ai_fallback_used", extra={"endpoint": "reply-options", "fallback_reason": "rate_limited"})
        opts = await _fallback_3_replies_localized((req.last_message or "").strip(), locale=locale, continue_mode=True)
        opts, quality = polish_many(opts[:3], locale=locale, max_len=220)
        if len(opts) != 3:
            logger.warning("ai_reply_options_only_one_returned", extra={"endpoint": "reply-options", "fallback_reason": "rate_limited", "count": len(opts)})
        return {"options": opts[:3], "meta": {"quality": quality[:3]}}

    last_message = (req.last_message or "").strip()
    ctx = [str(x or "").strip() for x in (req.conversation_context or []) if str(x or "").strip()][-10:]
    analysis = _analyze_reply_context(last_message, ctx)
    stage = str(analysis.get("stage") or "connection")
    preferred = (req.user_preferred_style or "").strip().lower()
    plan = SubscriptionService().get_active_plan(db, current_user.id)
    plan_tier = plan if plan in {"free", "premium", "premium_plus"} else "free"
    is_plus = plan_tier == "premium_plus"

    provider_used = "fallback"
    fallback_reason: str | None = None
    options: list[str] = []

    logger.info(
        "ai_request_started",
        extra={
            "endpoint": "reply-options",
            "ai_provider": settings.AI_PROVIDER,
            "ai_model": (settings.GEMINI_MODEL if settings.AI_PROVIDER == "gemini" else settings.AI_MODEL),
            "ctx_len": len(ctx),
        },
    )

    try:
        # Generate once; we'll map provider styles into the three required buckets.
        replies = await _with_timeout(
            generate_replies(
                last_message,
                ctx,
                user_style=preferred or "chill",
                allow_edgy_mode=False,
                locale=locale,
            )
        )
        # Provider result is list[dict{text, style}]
        friendly = None
        playful = None
        deeper = None
        for row in replies or []:
            if not isinstance(row, dict):
                continue
            text = str(row.get("text") or "").strip()
            style = str(row.get("style") or "").strip().lower()
            if not text:
                continue
            if friendly is None and style in {"safe"}:
                friendly = text
            elif playful is None and style in {"slightly_bold", "bold", "playful", "flirty"}:
                playful = text
            elif deeper is None and style in {"engaging", "deeper", "interesting"}:
                deeper = text
        # Fill in order with remaining texts.
        pool = [str(r.get("text") or "").strip() for r in (replies or []) if isinstance(r, dict)]
        pool = [p for p in pool if p]
        friendly = friendly or (pool[0] if len(pool) > 0 else "")
        playful = playful or (pool[1] if len(pool) > 1 else "")
        deeper = deeper or (pool[2] if len(pool) > 2 else "")
        if analysis.get("question"):
            # Answer-first bias for questions.
            friendly = _ensure_question(friendly, locale)
        if analysis.get("dry"):
            playful = _ensure_question(playful, locale)
        if analysis.get("emotional"):
            deeper = _ensure_question(deeper, locale)
        if stage == "ready":
            if locale == "uk" and "кав" not in deeper.lower():
                deeper = _ensure_question(
                    f"{deeper.rstrip('?')} З тобою було б цікаво випити каву — як тобі такий формат?", locale
                )
            elif locale == "ru" and "коф" not in deeper.lower():
                deeper = _ensure_question(f"{deeper.rstrip('?')} С тобой было бы классно выпить кофе, как тебе идея?", locale)
            elif locale == "en" and "coffee" not in deeper.lower():
                deeper = _ensure_question(f"{deeper.rstrip('?')} This feels like a coffee conversation offline - what do you think?", locale)
        # subtle micro-flirt ~30%
        if random.random() < 0.3:
            if locale == "uk":
                playful = _ensure_question(f"{playful.rstrip('?')} З тобою це звучить цікавіше, до речі - що скажеш?", locale)
            elif locale == "ru":
                playful = _ensure_question(f"{playful.rstrip('?')} С тобой это звучит интереснее, кстати - как тебе?", locale)
            else:
                playful = _ensure_question(f"{playful.rstrip('?')} Somehow this sounds better with you - what do you think?", locale)
        options = [_ensure_question(friendly, locale), _ensure_question(playful, locale), _ensure_question(deeper, locale)]
        provider_used = "gemini" if settings.AI_PROVIDER == "gemini" and bool((settings.GEMINI_API_KEY or "").strip()) else "provider"
    except asyncio.TimeoutError:
        fallback_reason = "timeout"
    except Exception:
        fallback_reason = "exception"

    if not options or len([o for o in options if o.strip()]) < 3:
        provider_used = "fallback"
        fallback_reason = fallback_reason or "empty"
        options = await _fallback_3_replies_localized(last_message, locale=locale, continue_mode=True)

    if len(options) < 3:
        logger.warning(
            "ai_reply_options_only_one_returned",
            extra={"endpoint": "reply-options", "provider_used": provider_used, "fallback_reason": fallback_reason, "count": len(options)},
        )
    options, quality = polish_many(options[:3], locale=locale, max_len=220)
    chat_rows = [{"role": ("them" if i % 2 == 0 else "me"), "text": t} for i, t in enumerate(ctx)]
    if last_message:
        chat_rows.append({"role": "them", "text": last_message})
    health = _conversation_health_heuristic(messages=chat_rows[-20:], locale=locale)
    meeting = _smart_meeting_engine(
        chat=chat_rows[-20:],
        locale=locale,
        health_score=int(health.get("health_score") or 50),
        attraction_level=str(health.get("attraction_level") or "medium"),
        drop_risk=str(health.get("drop_risk") or "medium"),
    )
    if bool(meeting.get("should_suggest")) and ((is_plus or plan_tier == "premium") or (plan_tier == "free" and random.random() < 0.18)):
        meet_line = _ensure_question_short(str(meeting.get("message") or ""))
        if meet_line:
            options[2] = meet_line
    scored = _best_reply_payload(options=options[:3], analysis=analysis, locale=locale)

    logger.info(
        "ai_chat_suggestions_generated",
        extra={
            "endpoint": "reply-options",
            "ai_provider": provider_used,
            "ai_model": (settings.GEMINI_MODEL if settings.AI_PROVIDER == "gemini" else settings.AI_MODEL),
            "options_count": len(options),
            "fallback_reason": fallback_reason,
        },
    )
    track_event(
        db,
        "ai_chat_suggestions_generated",
        user_id=current_user.id,
        payload={"provider": provider_used, "model": (settings.GEMINI_MODEL if settings.AI_PROVIDER == "gemini" else settings.AI_MODEL), "count": len(options)},
    )
    return {
        "options": options[:3],
        "best_reply": scored.get("best_reply"),
        "alternatives": scored.get("alternatives"),
        "why_best": scored.get("why_best"),
        "confidence": scored.get("confidence"),
        "stage": scored.get("stage"),
        "meta": {
            "quality": quality[:3],
            "analysis": analysis,
            "meeting": (
                {
                    "should_suggest": bool(meeting.get("should_suggest")),
                    "type": str(meeting.get("type") or "soft"),
                    "reason": str(meeting.get("reason") or "")[:180],
                    "confidence": int(meeting.get("confidence") or 0),
                    "best_moment": meeting.get("best_moment"),
                }
                if is_plus
                else {"should_suggest": bool(meeting.get("should_suggest"))}
            ),
        },
    }


@router.post("/reply", response_model=ReplyOptionsResponse)
async def reply_canonical(
    req: ReplyOptionsRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Canonical endpoint (product contract):
    - always returns 3 options
    - short (1–2 sentences)
    - always ends with a question
    - never auto-sends (UI rule)
    """
    res = await reply_options(req, current_user=current_user, db=db)
    raw_ui = getattr(req, "locale", None)
    loc = normalize_ai_request_locale(raw_ui or "en")
    opts = []
    try:
        opts = list((res or {}).get("options") or [])
    except Exception:
        opts = []
    fixed = normalize_triplet(opts, locale=loc, fallback=fallback_reply_triplet(locale=loc))
    fixed, quality = polish_many(fixed[:3], locale=loc, max_len=220)
    analysis = _analyze_reply_context(str(req.last_message or ""), [str(x or "") for x in (req.conversation_context or [])])
    scored = _best_reply_payload(options=fixed[:3], analysis=analysis, locale=loc)
    return {
        "options": fixed,
        "best_reply": scored.get("best_reply"),
        "alternatives": scored.get("alternatives"),
        "why_best": scored.get("why_best"),
        "confidence": scored.get("confidence"),
        "stage": scored.get("stage"),
        "meta": {"quality": quality[:3], "analysis": analysis},
    }


@router.post("/rewrite", response_model=ReplyOptionsResponse)
async def rewrite_canonical(
    req: ImproveReplyRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Canonical rewrite endpoint: returns 3 improved variants as `options`.
    """
    raw_ui = getattr(req, "locale", None)
    loc = normalize_ai_request_locale(raw_ui or "en")
    out = await wingman_improve_reply(req, current_user=current_user, db=db)
    rows = []
    try:
        rows = (out or {}).get("variants") or []
    except Exception:
        rows = []
    texts = [str((r or {}).get("text") or "").strip() for r in rows if isinstance(r, dict)]
    fixed = normalize_triplet(texts, locale=loc, fallback=fallback_reply_triplet(locale=loc))
    fixed, quality = polish_many(fixed[:3], locale=loc, max_len=220)
    return {"options": fixed, "meta": {"quality": quality[:3]}}


@router.post("/bio-suggest", response_model=ReplyOptionsResponse)
async def bio_suggest(
    req: BioSuggestRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Suggest 3 short bio options based on selected interests/tags.
    Keep it short, specific, and non-cringe. No questions required here.
    """
    raw_ui = getattr(req, "locale", None)
    loc = normalize_ai_request_locale(raw_ui or "en")
    tags = [str(x or "").strip() for x in (req.interests or []) if str(x or "").strip()][:6]
    city = str(getattr(req, "city", "") or "").strip()
    # Deterministic fallbacks (fast, always available).
    base = []
    if loc == "uk":
        base = [
            f"Люблю {', '.join(tags[:2]) if tags else 'каву і прогулянки'}. За легкі розмови, щирість і маленькі пригоди.",
            f"{city + ' · ' if city else ''}{' '.join([])}Шукаю людину, з якою можна і посміятись, і зірватись кудись спонтанно.",
            f"Мій вайб: {tags[0] if tags else 'затишок'} + {tags[1] if len(tags) > 1 else 'цікавість'}. Напиши, що тебе зараз надихає.",
        ]
    elif loc == "ru":
        base = [
            f"Люблю {', '.join(tags[:2]) if tags else 'кофе и прогулки'}. За лёгкие разговоры, честность и маленькие приключения.",
            f"{city + ' · ' if city else ''}Ищу человека, с которым можно и посмеяться, и сорваться куда-то спонтанно.",
            f"Мой вайб: {tags[0] if tags else 'уют'} + {tags[1] if len(tags) > 1 else 'любопытство'}. Напиши, что тебя сейчас вдохновляет.",
        ]
    else:
        base = [
            f"Into {', '.join(tags[:2]) if tags else 'coffee and long walks'}. I’m here for good banter, honesty, and small adventures.",
            f"{city + ' · ' if city else ''}Looking for someone to laugh with — and do something spontaneous once in a while.",
            f"My vibe: {tags[0] if tags else 'cozy'} + {tags[1] if len(tags) > 1 else 'curious'}. Tell me what you’re into lately.",
        ]
    # Best-effort AI upgrade (optional).
    try:
        if settings.ENABLE_AI_SUGGESTIONS and settings.AI_PROVIDER == "gemini" and (settings.GEMINI_API_KEY or "").strip():
            enforce_ai_limits(db, current_user.id)
            client = GeminiClient()
            system = (
                "You write dating app bios.\n"
                "Rules:\n"
                "- Return STRICT JSON: {\"options\": [\"...\", \"...\", \"...\"]}\n"
                "- 1–2 sentences each, max 220 chars\n"
                "- Use 1–2 interests naturally (no lists)\n"
                "- No generic lines like 'hi how are you'\n"
                "- No emojis spam (0–1 emoji ok)\n"
            )
            payload = {"interests": tags, "city": city, "locale": loc}
            out = await client.generate_json(system_prompt=system, user_prompt=f"INPUT_JSON:\n{payload}", temperature=0.55, max_output_tokens=240)
            opts = out.get("options") if isinstance(out, dict) else None
            if isinstance(opts, list):
                cleaned = [" ".join((str(x or "").strip()).split())[:220] for x in opts if str(x or "").strip()]
                if len(cleaned) >= 3:
                    return {"options": cleaned[:3]}
    except Exception:
        pass
    return {"options": [x[:220] for x in base][:3]}


@router.post("/timing", response_model=TimedRepliesResponse)
async def timing_canonical(
    req: TimedRepliesRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Canonical timing endpoint: returns 3 short nudge options (light/flirty/deep) for the given nudge_type.
    Wrapper over /timed-replies to keep client contract stable.
    """
    return await timed_replies(req, current_user=current_user, db=db)


@router.post("/analyze")
async def wingman_analyze(
    req: AnalyzeConversationRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not settings.ENABLE_AI_SUGGESTIONS:
        return {"analysis": {}}
    try:
        enforce_ai_limits(db, current_user.id)
    except RateLimitExceeded:
        return {"analysis": {}}
    return {"analysis": await analyze_conversation(req.messages)}


@router.post("/interest-stage", response_model=InterestStageResponse)
async def interest_stage(
    req: AnalyzeConversationRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        enforce_ai_limits(db, current_user.id)
    except RateLimitExceeded:
        return _interest_stage_fallback(req.messages)

    if not settings.ENABLE_AI_SUGGESTIONS or settings.AI_PROVIDER != "gemini" or not (settings.GEMINI_API_KEY or "").strip():
        return _interest_stage_fallback(req.messages)

    system = (
        "You are NEYRA AI.\n"
        "Analyze conversation.\n"
        "Return STRICT JSON:\n"
        "{\n"
        '  \"interest_score\": 0-100,\n'
        '  \"stage\": \"cold\" | \"warming\" | \"engaged\" | \"ready\",\n'
        '  \"mutuality_score\": 0-100,\n'
        '  \"signals\": []\n'
        "}\n"
        "Mutuality rules:\n"
        "- High mutuality: both ask questions, both expand answers, emotional engagement from both sides.\n"
        "- Low mutuality: only one side asks, short replies, no follow-up questions.\n"
        "Do not add extra keys."
    )
    payload = {"messages": req.messages}

    async def _interest_stage_gemini() -> dict:
        client = GeminiClient()
        out = await client.generate_json(system_prompt=system, user_prompt=f"INPUT_JSON:\n{payload}", temperature=0.25, max_output_tokens=220)
        if not isinstance(out, dict):
            raise ValueError("invalid_interest_stage_shape")
        try:
            interest = int(out.get("interest_score"))
        except Exception:
            interest = 0
        try:
            mutual = int(out.get("mutuality_score"))
        except Exception:
            mutual = 0
        stage = str(out.get("stage") or "").strip().lower()
        if stage not in {"cold", "warming", "engaged", "ready"}:
            stage = "warming" if interest >= 35 else "cold"
        sig = out.get("signals") if isinstance(out.get("signals"), list) else []
        signals = [str(s or "").strip() for s in sig if str(s or "").strip()][:10]
        return {
            "interest_score": max(0, min(100, interest)),
            "stage": stage,
            "mutuality_score": max(0, min(100, mutual)),
            "signals": signals,
        }

    async def _interest_stage_fb() -> dict:
        return _interest_stage_fallback(req.messages)

    return await safe_ai_generate_async(
        _interest_stage_gemini,
        _interest_stage_fb,
        endpoint="interest-stage",
        locale="en",
    )


@router.post("/timing-engine", response_model=TimingEngineResponse)
async def timing_engine(
    req: TimingEngineRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        enforce_ai_limits(db, current_user.id)
    except RateLimitExceeded:
        return _timing_engine_fallback(req)

    if not settings.ENABLE_AI_SUGGESTIONS or settings.AI_PROVIDER != "gemini" or not (settings.GEMINI_API_KEY or "").strip():
        return _timing_engine_fallback(req)

    system = (
        "You are NEYRA AI Timing Engine.\n"
        "Goal: Decide if the user should send a message now or wait.\n"
        "Rules:\n"
        "- Good to send NOW if partner usually replies at this hour, last latency window passed (>= avg_reply), conversation is engaged, and no double text within 15–30 min.\n"
        "- Wait if user just sent a message (< 15–30 min) or partner is a slow responder and window not reached, or late night mismatch.\n"
        "- Re-engage if no reply for 12–48h.\n"
        "Return STRICT JSON only:\n"
        "{\n"
        '  \"should_send_now\": true/false,\n'
        '  \"confidence\": 0-100,\n'
        '  \"nudge_type\": \"now\" | \"wait\" | \"reengage\" | \"revive\",\n'
        '  \"best_time_window\": \"e.g. today 18:00-21:00\",\n'
        '  \"reasoning\": \"short human explanation\"\n'
        "}\n"
        "Do not add extra keys."
    )
    payload = {
        "messages": req.messages,
        "last_message_at": req.last_message_at,
        "avg_partner_reply_minutes": req.avg_partner_reply_minutes,
        "partner_active_hours": req.partner_active_hours,
        "stall_score": req.stall_score,
        "interest_stage": req.interest_stage,
        "mutuality_score": req.mutuality_score,
    }
    loc_te = str(getattr(req, "locale", None) or "en")[:12]

    async def _timing_engine_gemini() -> dict:
        client = GeminiClient()
        out = await client.generate_json(
            system_prompt=system,
            user_prompt=f"INPUT_JSON:\n{payload}",
            temperature=0.2,
            max_output_tokens=260,
            surface="timing-engine",
        )
        if not isinstance(out, dict):
            raise ValueError("invalid_timing_engine_shape")
        should_send_now = bool(out.get("should_send_now"))
        try:
            confidence = int(out.get("confidence"))
        except Exception:
            confidence = 0
        nudge_type = str(out.get("nudge_type") or "").strip().lower()
        if nudge_type not in {"now", "wait", "reengage", "revive"}:
            nudge_type = "wait"
        best_time_window = str(out.get("best_time_window") or "").strip()[:64]
        reasoning = str(out.get("reasoning") or "").strip()[:220]
        return {
            "should_send_now": should_send_now,
            "confidence": max(0, min(100, confidence)),
            "nudge_type": nudge_type,
            "best_time_window": best_time_window,
            "reasoning": reasoning,
        }

    async def _timing_engine_fb() -> dict:
        return _timing_engine_fallback(req)

    return await safe_ai_generate_async(
        _timing_engine_gemini,
        _timing_engine_fb,
        endpoint="timing-engine",
        locale=loc_te,
    )


@router.post("/timed-replies", response_model=TimedRepliesResponse)
async def timed_replies(
    req: TimedRepliesRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from app.services.ai.output_script_locale import sniff_dominant_script_for_log

    raw_ui = getattr(req, "locale", None)
    hint_raw = str(getattr(req, "language_hint", None) or "").strip() or None
    latest_user_message = next(
        (str((m or {}).get("text") or "").strip() for m in reversed(req.messages or []) if str((m or {}).get("role") or "").strip().lower() == "me" and str((m or {}).get("text") or "").strip()),
        "",
    )
    latest_partner_message = next(
        (str((m or {}).get("text") or "").strip() for m in reversed(req.messages or []) if str((m or {}).get("role") or "").strip().lower() == "them" and str((m or {}).get("text") or "").strip()),
        "",
    )
    latest_for_locale_hint = latest_partner_message or latest_user_message
    loc = _resolve_ai_locale_for_request(
        req_locale=raw_ui,
        ai_locale=getattr(req, "ai_locale", None),
        request=request,
        db=db,
        current_user=current_user,
        latest_user_message=latest_for_locale_hint,
        prefer_message_locale=True,
        route_label="POST /ai/timed-replies",
    )
    log_ai_locale_context(
        logger,
        endpoint="timed-replies",
        ui_locale=raw_ui,
        ai_locale=loc,
        language_hint=hint_raw,
        source="request",
        fallback_used=False,
    )
    logger.info("AI locale used: %s", loc)

    def _emit_timed_locale_log(options: list[dict], *, source: str) -> None:
        joined = " ".join(str(o.get("text") or "") for o in (options or []))
        _guess_tr = sniff_dominant_script_for_log(joined)
        log_ai_locale_result(
            logger,
            endpoint="timed-replies",
            requested_locale=str(raw_ui) if raw_ui is not None else None,
            normalized_locale=loc,
            returned_language=_guess_tr,
            fallback_used=source != "ai",
            cache_hit=False,
            source=source,
        )
        log_ai_response_debug(
            route="POST /ai/timed-replies",
            resolved_locale=loc,
            fallback_used=source != "ai",
            cache_hit=False,
            output_language_guess=_guess_tr,
        )

    nudge = (req.nudge_type or "").strip().lower()
    if nudge == "wait":
        _emit_timed_locale_log([], source="ai")
        return {"options": [], "locale": loc, "source": "ai"}
    if nudge not in {"now", "reengage", "revive"}:
        raise HTTPException(status_code=400, detail="Invalid nudge_type")

    from app.services.ai.conversation_goal_engine import hours_since_iso as _hours_since_iso_tr

    _h_pre = _hours_since_iso_tr(str(getattr(req, "last_message_at", None) or "").strip() or None)
    _chat_pre = _format_chat_context(req.messages or [], max_messages=48)
    closer_stage_pass = _closer_stage_for_timed_replies_chat(_chat_pre, hours_since_last=_h_pre)

    try:
        plan_tier, _ = enforce_and_consume_ai_usage(db, user_id=int(current_user.id), usage_type="message")
    except AiNotUnlocked:
        _raise_ai_unlock_after_match()
    except AiLimitReached:
        _raise_ai_limit_hit()
    except AiRapidCooldown:
        opts_fb = await _timed_replies_fallback_i18n(
            req.messages or [], nudge_type=nudge, locale=loc, closer_stage=closer_stage_pass
        )
        _emit_timed_locale_log(opts_fb, source="fallback")
        return {
            "options": _attach_structured_to_timed_options(opts_fb),
            "locale": loc,
            "source": "fallback",
            "goal_metrics": None,
        }
    stage_g = (req.interest_stage or "").strip().lower()
    mutual_g = int(req.mutuality_score or 0)

    from app.services.ai.conversation_goal_engine import (
        compute_conversation_goal_state,
        goal_state_prompt_block,
        premium_plus_goal_metrics_public,
        hours_since_iso,
    )

    def _timed_goal_metrics(messages_src: list[dict]) -> dict | None:
        if plan_tier != "premium_plus":
            return None
        cc = _format_chat_context(messages_src or [], max_messages=message_context_limit(plan_tier))
        h_mm = hours_since_iso(str(getattr(req, "last_message_at", None) or "").strip() or None)
        w_raw = str(getattr(req, "who_sent_last", None) or "").strip().lower()
        w_ok = w_raw if w_raw in {"me", "them"} else None
        gst = compute_conversation_goal_state(
            cc,
            plan_tier=plan_tier,
            locale=loc,
            hours_since_last_message=h_mm,
            who_sent_last=w_ok,
            nudge_type=nudge,
            interest_stage=stage_g,
            mutuality_score=mutual_g,
        )
        return premium_plus_goal_metrics_public(gst, locale=loc)

    if plan_tier == "free":
        opts_fb = await _timed_replies_fallback_i18n(
            req.messages or [], nudge_type=nudge, locale=loc, closer_stage=closer_stage_pass
        )
        _emit_timed_locale_log(opts_fb, source="fallback")
        return {
            "options": _attach_structured_to_timed_options(opts_fb),
            "locale": loc,
            "source": "fallback",
            "goal_metrics": _timed_goal_metrics(req.messages or []),
        }

    if plan_tier == "free" and nudge == "revive":
        st = _daily_boosts_get(db, user_id=int(current_user.id))
        if bool(st.get("revive_used")):
            raise HTTPException(status_code=402, detail=api_error("paywall.ai_revive_daily_limit", max=1))

    if plan_tier == "free" and nudge == "now":
        stq = _daily_boosts_get(db, user_id=int(current_user.id))
        if int(stq.get("reply_uses") or 0) >= int(FREE_TIER_AI_REPLY_SLOTS_PER_DAY):
            opts_fb = await _timed_replies_fallback_i18n(
                req.messages or [], nudge_type=nudge, locale=loc, closer_stage=closer_stage_pass
            )
            _emit_timed_locale_log(opts_fb, source="fallback_quota")
            return {
                "options": _attach_structured_to_timed_options(opts_fb),
                "locale": loc,
                "source": "fallback_quota",
                "goal_metrics": _timed_goal_metrics(req.messages or []),
            }

    # Apply limits (premium users have more quota).
    try:
        enforce_ai_limits(db, current_user.id)
    except RateLimitExceeded:
        opts_fb = await _timed_replies_fallback_i18n(
            req.messages or [], nudge_type=nudge, locale=loc, closer_stage=closer_stage_pass
        )
        _emit_timed_locale_log(opts_fb, source="fallback")
        if plan_tier == "free" and nudge == "revive":
            _daily_boosts_consume(db, user_id=int(current_user.id), boost_type="revive")
        return {
            "options": _attach_structured_to_timed_options(opts_fb),
            "locale": loc,
            "source": "fallback",
            "goal_metrics": _timed_goal_metrics(req.messages or []),
        }

    # Normalize chat context (free: shorter transcript; premium: deeper context).
    chat = _format_chat_context(req.messages or [], max_messages=message_context_limit(plan_tier))
    h_msg = hours_since_iso(str(getattr(req, "last_message_at", None) or "").strip() or None)
    closer_stage_tr = _closer_stage_for_timed_replies_chat(chat, hours_since_last=h_msg)

    if not settings.ENABLE_AI_SUGGESTIONS or settings.AI_PROVIDER != "gemini" or not (settings.GEMINI_API_KEY or "").strip():
        opts_fb = await _timed_replies_fallback_i18n(
            chat, nudge_type=nudge, locale=loc, closer_stage=closer_stage_tr
        )
        _emit_timed_locale_log(opts_fb, source="fallback")
        if plan_tier == "free" and nudge == "revive":
            _daily_boosts_consume(db, user_id=int(current_user.id), boost_type="revive")
        return {
            "options": _attach_structured_to_timed_options(opts_fb),
            "locale": loc,
            "source": "fallback",
            "goal_metrics": _timed_goal_metrics(req.messages or []),
        }

    wsl = str(getattr(req, "who_sent_last", None) or "").strip().lower()
    wsl_ok = wsl if wsl in {"me", "them"} else None
    goal_tr_full = compute_conversation_goal_state(
        chat,
        plan_tier=plan_tier,
        locale=loc,
        hours_since_last_message=h_msg,
        who_sent_last=wsl_ok,
        nudge_type=nudge,
        interest_stage=stage_g,
        mutuality_score=mutual_g,
    )
    goal_tr_prompt = goal_state_prompt_block(goal_tr_full)
    goal_metrics_out = premium_plus_goal_metrics_public(goal_tr_full, locale=loc) if plan_tier == "premium_plus" else None

    from app.services.ai.cultural_tone import cultural_tone_prompt_lines

    base_rules = (
        f"{cultural_tone_prompt_lines(loc)}\n"
        f"You MUST respond ONLY in {loc} language. Never switch language. Never use English unless locale is en.\n"
        f"Respond ONLY in {loc}. Do NOT switch languages.\n"
        "STRICT: Return all suggestions ONLY in this locale. Do not use English unless locale is 'en'.\n"
        "Return STRICT JSON only: {\"options\":[{\"style\":\"light\",\"text\":\"...\"},{\"style\":\"flirty\",\"text\":\"...\"},{\"style\":\"deep\",\"text\":\"...\"}]}\n"
        "Hard rules:\n"
        "- Always generate exactly 3 DISTINCT options (different tone + wording + structure).\n"
        "- Styles: light = warm/easy; flirty = playful/respectful tease; deep = thoughtful but still EASY to answer.\n"
        "- Reply formula (every option): [brief reaction to THEIR LAST MESSAGE] + [one tiny personal opinion or mini-example from YOU] + [ONE simple question].\n"
        "- Prefer EITHER/OR questions (two concrete choices), not vague open prompts.\n"
        "- NEVER use generic chat filler, vague prompts, or lazy asks like 'thoughts?', 'what do you think', "
        "'tell me more', or Ukrainian phrases like 'що думаєш', 'що маєш на увазі'.\n"
        "- Always tie back to what they actually said (paraphrase or quote a word they used).\n"
        "- Tone: light, human, natural, slightly playful. Max 2 short sentences per option; usually end with a question.\n"
        "- Exception at advanced rapport (soft meeting hint): one option may be observational/reassuring without a question — never imperative scheduling.\n"
        "- No cringe, no pickup lines, no pressure to meet too early. No sexual content. No manipulation.\n"
        "- Emojis allowed sparingly when they fit the dating-chat tone.\n"
    )

    if nudge == "now":
        goal = "Normal copilot replies to continue the conversation naturally; keep momentum and invite a reply."
    elif nudge == "reengage":
        goal = (
            "Restart conversation lightly after a pause, no pressure, no 'why didn’t you reply'. "
            "Include at least one playful or curious angle and one clear easy question."
        )
    else:
        goal = (
            "Revive a stalling conversation: topic shift, personal hook, playful line — avoid dead ends; "
            "at least one option should be a simple question, one slightly playful."
        )

    if goal_tr_full.drop_risk > 60 and nudge == "now":
        goal = (
            goal
            + " REENGAGE_BIAS: thread may be cooling — favor warmth, novelty, and an easy curiosity hook; "
            "avoid pushing an in-person meet until engagement recovers."
        )

    if closer_stage_tr == "ready_for_meeting" and nudge == "now":
        goal = (
            goal
            + " MEETING_SOFT_LADDER: steer toward an eventual low-pressure in-person continuation using observer framing → gentle coffee/walk idea → reassurance; "
            "never commands like 'let's meet' / 'давай зустрінемось'."
        )

    from app.services.ai.tier_prompting import capability_prompt_block

    system = (
        "You are NEYRA Copilot (conversation coach).\n"
        f"Goal: {goal}\n"
        f"Inputs summary: interest_stage={stage_g or 'unknown'}, mutuality_score={mutual_g}, closer_stage={closer_stage_tr}.\n"
        + base_rules
        + capability_prompt_block(plan_tier)
        + goal_tr_prompt
        + closer_timed_replies_prompt_addon(closer_stage_tr, loc)
    )
    hint = str(getattr(req, "language_hint", None) or "").strip()
    payload = {
        "messages": chat,
        "nudge_type": nudge,
        "interest_stage": stage_g,
        "mutuality_score": mutual_g,
        "locale": loc,
        "language_hint": hint or None,
    }

    try:
        client = GeminiClient()
        out = await client.generate_json(
            system_prompt=system,
            user_prompt=f"INPUT_JSON:\n{payload}",
            temperature=0.75 if nudge != "now" else 0.7,
            max_output_tokens=420,
            surface="timed-replies",
        )
        rows = out.get("options") if isinstance(out, dict) else None
        if not isinstance(rows, list):
            opts_fb = await _timed_replies_fallback_i18n(
                chat, nudge_type=nudge, locale=loc, closer_stage=closer_stage_tr
            )
            _emit_timed_locale_log(opts_fb, source="fallback")
            if plan_tier == "free" and nudge == "revive":
                _daily_boosts_consume(db, user_id=int(current_user.id), boost_type="revive")
            return {
                "options": _attach_structured_to_timed_options(opts_fb),
                "locale": loc,
                "source": "fallback",
                "goal_metrics": goal_metrics_out,
            }
        opts: list[dict] = []
        for r in rows[:3]:
            if not isinstance(r, dict):
                continue
            style = str(r.get("style") or "").strip().lower()
            style = "flirty" if style == "flirty" else "deep" if style == "deep" else "light"
            text = polish_timed_fallback_line(str(r.get("text") or "").strip(), closer_stage=closer_stage_tr)
            if not text:
                continue
            opts.append({"style": style, "text": text})
        if len(opts) != 3 or _diversity_score([o["text"] for o in opts]) < 0.12:
            opts_fb = await _timed_replies_fallback_i18n(
                chat, nudge_type=nudge, locale=loc, closer_stage=closer_stage_tr
            )
            _emit_timed_locale_log(opts_fb, source="fallback")
            if plan_tier == "free" and nudge == "revive":
                _daily_boosts_consume(db, user_id=int(current_user.id), boost_type="revive")
            return {
                "options": _attach_structured_to_timed_options(opts_fb),
                "locale": loc,
                "source": "fallback",
                "goal_metrics": goal_metrics_out,
            }
        from app.services.ai.ai_fallback_phrases import timed_now_emergency_triple
        from app.services.ai.output_script_locale import text_matches_requested_locale

        emergency = timed_now_emergency_triple(loc)
        fixed = await _enforce_ai_texts_locale_once([str(o.get("text") or "").strip() for o in opts], locale=loc)
        for i, o in enumerate(opts):
            cand = str(fixed[i] if i < len(fixed) else o.get("text") or "").strip()
            if cand and text_matches_requested_locale(cand, loc):
                o["text"] = polish_timed_fallback_line(cand, closer_stage=closer_stage_tr)
            else:
                o["text"] = polish_timed_fallback_line(emergency[min(i, 2)], closer_stage=closer_stage_tr)
        _emit_timed_locale_log(opts, source="ai")
        if plan_tier == "free" and nudge == "now":
            _daily_boosts_consume(db, user_id=int(current_user.id), boost_type="reply")
        if plan_tier == "free" and nudge == "revive":
            _daily_boosts_consume(db, user_id=int(current_user.id), boost_type="revive")
        return {"options": _attach_structured_to_timed_options(opts), "locale": loc, "source": "ai", "goal_metrics": goal_metrics_out}
    except asyncio.TimeoutError as e:
        _log_ai_fallback("timed-replies", reason="TimeoutError", locale=loc, exc=e)
        opts_fb = await _timed_replies_fallback_i18n(
            chat, nudge_type=nudge, locale=loc, closer_stage=closer_stage_tr
        )
        _emit_timed_locale_log(opts_fb, source="fallback")
        if plan_tier == "free" and nudge == "revive":
            _daily_boosts_consume(db, user_id=int(current_user.id), boost_type="revive")
        return {
            "options": _attach_structured_to_timed_options(opts_fb),
            "locale": loc,
            "source": "fallback",
            "goal_metrics": goal_metrics_out,
        }
    except GeminiError as e:
        _log_ai_fallback("timed-replies", reason=str(getattr(e, "code", "") or "GeminiError"), locale=loc, exc=e)
        opts_fb = await _timed_replies_fallback_i18n(
            chat, nudge_type=nudge, locale=loc, closer_stage=closer_stage_tr
        )
        _emit_timed_locale_log(opts_fb, source="fallback")
        if plan_tier == "free" and nudge == "revive":
            _daily_boosts_consume(db, user_id=int(current_user.id), boost_type="revive")
        return {
            "options": _attach_structured_to_timed_options(opts_fb),
            "locale": loc,
            "source": "fallback",
            "goal_metrics": goal_metrics_out,
        }
    except Exception as e:
        _log_ai_fallback("timed-replies", reason=type(e).__name__, locale=loc, exc=e)
        opts_fb = await _timed_replies_fallback_i18n(
            chat, nudge_type=nudge, locale=loc, closer_stage=closer_stage_tr
        )
        _emit_timed_locale_log(opts_fb, source="fallback")
        if plan_tier == "free" and nudge == "revive":
            _daily_boosts_consume(db, user_id=int(current_user.id), boost_type="revive")
        return {
            "options": _attach_structured_to_timed_options(opts_fb),
            "locale": loc,
            "source": "fallback",
            "goal_metrics": goal_metrics_out,
        }


@router.post("/timing-decision", response_model=TimingDecisionResponse)
def timing_decision(
    req: TimingDecisionRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from datetime import UTC, datetime

    rows = []
    partner_user_id = int(req.partner_user_id) if getattr(req, "partner_user_id", None) else None
    if partner_user_id:
        if is_blocked(db, current_user.id, partner_user_id):
            raise HTTPException(status_code=403, detail=api_error("chat.user_blocked"))
        if not users_are_matched(db, current_user.id, partner_user_id):
            raise HTTPException(status_code=403, detail=api_error("chat.match_required"))

        rows = (
            db.query(Message)
            .filter(
                ((Message.sender_id == current_user.id) & (Message.receiver_id == partner_user_id))
                | ((Message.sender_id == partner_user_id) & (Message.receiver_id == current_user.id))
            )
            .order_by(Message.created_at.asc())
            .limit(200)
            .all()
        )

    now = datetime.now(UTC)
    last_dt = rows[-1].created_at if rows else None
    if last_dt is None and getattr(req, "last_message_at", None):
        try:
            last_dt = datetime.fromisoformat(str(getattr(req, "last_message_at")).replace("Z", "+00:00"))
        except Exception:
            last_dt = None
    if last_dt is not None and getattr(last_dt, "tzinfo", None) is None:
        last_dt = last_dt.replace(tzinfo=UTC)
    minutes_since_last = int(max(0.0, float((now - last_dt).total_seconds()) / 60.0)) if last_dt is not None else 0
    who_sent_last = None
    if rows:
        who_sent_last = "me" if int(rows[-1].sender_id) == int(current_user.id) else "them"
    else:
        wsl = str(getattr(req, "who_sent_last", "") or "").strip().lower()
        who_sent_last = "me" if wsl == "me" else "them" if wsl == "them" else None

    avg_reply = _avg_partner_reply_minutes(rows, viewer_id=current_user.id, partner_id=partner_user_id) if partner_user_id else None
    if avg_reply is None and getattr(req, "reply_time_avg", None) is not None:
        try:
            avg_reply = float(getattr(req, "reply_time_avg"))
        except Exception:
            avg_reply = None
    avg_reply_i = int(max(0.0, float(avg_reply))) if avg_reply is not None else 0
    active_hours = _partner_active_hours(rows, partner_id=partner_user_id) if partner_user_id else []

    # Use provided AI signals if present; otherwise infer quickly from chat.
    interest_stage = (req.interest_stage or "").strip().lower()
    mutuality_score = int(req.mutuality_score or 0)
    stall_score = int(req.stall_score or 0)
    if not interest_stage or mutuality_score <= 0:
        try:
            chat = _format_chat_context([{"role": ("me" if int(m.sender_id) == int(current_user.id) else "them"), "text": (m.content or "")} for m in rows][-50:], max_messages=50)
            meta = _interest_stage_from_chat(chat)
            if not interest_stage:
                interest_stage = str(meta.get("stage") or "")
            if mutuality_score <= 0:
                mutuality_score = int(meta.get("mutuality_score") or 0)
        except Exception:
            pass

    from app.services.app_language import normalize_app_language

    loc = normalize_app_language(getattr(req, "locale", None) or "en")
    if loc not in {"en", "uk", "ru"}:
        loc = "en"

    # Decision rules (must-have)
    nudge_type = "wait"
    reasoning = (
        "Better to wait a little so it does not feel like spam."
        if loc == "en"
        else "Лучше чуть подождать, чтобы это не выглядело как спам."
        if loc == "ru"
        else "Краще трохи зачекати, щоб це не виглядало як спам."
    )
    should_send_now = False
    confidence = 60

    if who_sent_last == "me" and minutes_since_last < 30:
        nudge_type = "wait"
        should_send_now = False
        confidence = 88
        reasoning = (
            "You just sent a message — better to give them time to reply."
            if loc == "en"
            else "Ты только что написал(а) — лучше дать человеку время ответить."
            if loc == "ru"
            else "Ти щойно написав(ла) — краще дати людині час відповісти."
        )
    elif minutes_since_last >= 12 * 60 and minutes_since_last <= 48 * 60:
        nudge_type = "reengage"
        should_send_now = True
        confidence = 78
        reasoning = (
            "There’s been a pause — you can restart gently without pressure."
            if loc == "en"
            else "Есть пауза — можно мягко перезапустить разговор без давления."
            if loc == "ru"
            else "Є пауза — можна м’яко перезапустити розмову без тиску."
        )
    elif stall_score >= 65:
        nudge_type = "revive"
        should_send_now = True
        confidence = 74
        reasoning = (
            "The chat is stalling — it’s better to change approach and switch topics."
            if loc == "en"
            else "Разговор проседает — лучше сменить ход и зайти с другой темы."
            if loc == "ru"
            else "Розмова просідає — краще змінити хід і зайти з іншої теми."
        )
    elif interest_stage in {"engaged", "ready"} and mutuality_score >= 60:
        nudge_type = "now"
        should_send_now = True
        confidence = 80
        reasoning = (
            "It’s a good moment now: there’s mutual interest and the chat is flowing."
            if loc == "en"
            else "Сейчас хороший момент: есть взаимный интерес и разговор держится."
            if loc == "ru"
            else "Зараз нормальний момент: є взаємний інтерес і розмова тримається."
        )
    else:
        nudge_type = "wait"
        should_send_now = False
        confidence = 62

    best_time_window = ""
    if active_hours:
        if loc == "en":
            best_time_window = f"today {min(active_hours):02d}:00–{max(active_hours):02d}:00"
        elif loc == "ru":
            best_time_window = f"сегодня {min(active_hours):02d}:00–{max(active_hours):02d}:00"
        else:
            best_time_window = f"сьогодні {min(active_hours):02d}:00–{max(active_hours):02d}:00"

    track_event(
        db,
        "ai_timing_decision_requested",
        user_id=current_user.id,
        payload={
            "partner_user_id": partner_user_id,
            "nudge_type": nudge_type,
            "should_send_now": should_send_now,
            "confidence": confidence,
            "minutes_since_last_message": minutes_since_last,
            "avg_partner_reply_minutes": avg_reply_i,
        },
    )

    # Requested higher-level decision:
    # wait | now | revive | escalate
    decision = "wait"
    if nudge_type == "revive" or minutes_since_last >= 24 * 60:
        decision = "revive"
    elif nudge_type in {"now", "reengage"} and should_send_now:
        msg_count = 0
        try:
            msg_count = int(getattr(req, "message_count", 0) or 0)
        except Exception:
            msg_count = 0
        if msg_count <= 0:
            msg_count = len(rows) if rows else 0
        convo_len = 0
        try:
            convo_len = int(getattr(req, "conversation_length", 0) or 0)
        except Exception:
            convo_len = 0
        if convo_len <= 0:
            convo_len = msg_count
        if interest_stage in {"engaged", "ready"} and mutuality_score >= 70 and convo_len >= 10 and who_sent_last == "them" and minutes_since_last <= 180:
            decision = "escalate"
            confidence = min(95, max(int(confidence), 82))
        else:
            decision = "now"

    return {
        "should_send_now": should_send_now,
        "confidence": confidence,
        "nudge_type": nudge_type,
        "best_time_window": best_time_window,
        "reasoning": reasoning,
        "metrics": {
            "minutes_since_last_message": minutes_since_last,
            "avg_partner_reply_minutes": avg_reply_i,
            "mutuality_score": int(max(0, min(100, mutuality_score))),
            "stall_score": int(max(0, min(100, stall_score))),
        },
        "decision": decision,
    }


@router.post("/combo", response_model=ComboResponse)
async def ai_combo(
    req: ComboRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from app.services.app_language import resolve_ai_request_locale

    combo_locale = resolve_ai_request_locale(getattr(req, "locale", None))

    partner_user_id = int(req.partner_user_id)
    if is_blocked(db, current_user.id, partner_user_id):
        raise HTTPException(status_code=403, detail=api_error("chat.user_blocked"))
    if not users_are_matched(db, current_user.id, partner_user_id):
        raise HTTPException(status_code=403, detail=api_error("chat.match_required"))

    # Pull canonical chat from DB (do not trust frontend-only messages).
    rows = (
        db.query(Message)
        .filter(
            ((Message.sender_id == current_user.id) & (Message.receiver_id == partner_user_id))
            | ((Message.sender_id == partner_user_id) & (Message.receiver_id == current_user.id))
        )
        .order_by(Message.created_at.desc())
        .limit(80)
        .all()
    )
    rows.reverse()
    chat: list[dict] = []
    for m in rows:
        role = "me" if int(m.sender_id) == int(current_user.id) else "them"
        text = (m.content or "").strip()
        if not text and getattr(m, "voice_url", None):
            text = "[voice message]"
        if not text:
            continue
        chat.append({"role": role, "text": text})
    chat = _format_chat_context(chat, max_messages=50)

    # Step 1: interest + mutuality + stage (role-aware)
    stage_meta = _interest_stage_from_chat(chat)
    interest_score = int(stage_meta.get("interest_score") or 0)
    stage = str(stage_meta.get("stage") or "cold")
    mutuality_score = int(stage_meta.get("mutuality_score") or 0)

    # Step 2: stall
    stall_meta = _detect_stall_fallback(chat, hours_since_last=None)
    stall_score = int(stall_meta.get("stall_score") or 0)
    is_stalled = bool(stall_meta.get("is_stalled"))

    # Step 3: timing decision (reuse same must-have rules as /timing-decision)
    # Compute minutes since last and who sent last.
    from datetime import UTC, datetime

    now = datetime.now(UTC)
    last_dt = rows[-1].created_at if rows else None
    if last_dt is not None and getattr(last_dt, "tzinfo", None) is None:
        last_dt = last_dt.replace(tzinfo=UTC)
    minutes_since_last = int(max(0.0, float((now - last_dt).total_seconds()) / 60.0)) if last_dt is not None else 0
    who_sent_last = "me" if rows and int(rows[-1].sender_id) == int(current_user.id) else "them"

    nudge_type = "wait"
    confidence = 62
    if who_sent_last == "me" and minutes_since_last < 30:
        nudge_type = "wait"
        confidence = 88
    elif minutes_since_last >= 12 * 60 and minutes_since_last <= 48 * 60:
        nudge_type = "reengage"
        confidence = 78
    elif stall_score >= 65:
        nudge_type = "revive"
        confidence = 74
    elif stage in {"engaged", "ready"} and mutuality_score >= 60:
        nudge_type = "now"
        confidence = 80
    else:
        nudge_type = "wait"
        confidence = 62

    # Step 4: meeting readiness (cheap heuristic)
    meeting_readiness = int(_meeting_readiness_heuristic(chat, is_premium=True))

    closer_combo = _closer_stage_for_timed_replies_chat(chat, hours_since_last=None)

    # Decision logic (as requested)
    options: list[dict] = []
    meeting_allowed = bool(meeting_readiness > 75 and mutuality_score > 65)
    meeting_suggestions: list[str] = []

    if nudge_type == "wait":
        options = []
    else:
        # Prefer revive on stall, otherwise use timing type.
        effective = "revive" if is_stalled else ("reengage" if nudge_type == "reengage" else "now")
        options = await _timed_replies_fallback_i18n(
            chat, nudge_type=effective, locale=combo_locale, closer_stage=closer_combo
        )
        # Ensure exactly 3 options for non-wait.
        if len(options) != 3:
            options = await _timed_replies_fallback_i18n(
                chat, nudge_type="now", locale=combo_locale, closer_stage=closer_combo
            )
        if meeting_allowed and effective == "now":
            # Optional + safe, no pressure.
            meeting_suggestions = _meeting_options_fallback(readiness=meeting_readiness).get("meeting_options", [])[:2]

    ui = _combo_ui(nudge_type, stage=stage, mutuality=mutuality_score, stall_score=stall_score)

    track_event(
        db,
        "ai_combo_requested",
        user_id=current_user.id,
        payload={
            "partner_user_id": partner_user_id,
            "nudge_type": nudge_type,
            "stage": stage,
            "mutuality_score": mutuality_score,
            "meeting_allowed": meeting_allowed,
        },
    )

    return {
        "decision": {"nudge_type": nudge_type, "confidence": confidence},
        "signals": {
            "interest_score": max(0, min(100, interest_score)),
            "stage": stage,
            "mutuality_score": max(0, min(100, mutuality_score)),
            "stall_score": max(0, min(100, stall_score)),
            "meeting_readiness": max(0, min(100, meeting_readiness)),
        },
        "ui": ui,
        "options": options if nudge_type != "wait" else [],
        "meeting": {"allowed": meeting_allowed, "suggestions": meeting_suggestions},
    }


@router.post("/readiness-score", response_model=ReadinessScoreResponse)
def readiness_score(
    req: ReadinessScoreRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    plan = SubscriptionService().get_active_plan(db, current_user.id)
    plan_tier = plan if plan in {"free", "premium", "premium_plus"} else "free"
    # Deterministic + fast: no quota enforcement.
    result = score_readiness(
        messages=[{"role": m.role, "text": m.text} for m in (req.messages or [])],
        draft=req.draft,
        plan_tier=plan_tier,
        locale=req.locale,
    )
    tips = result.tips if plan_tier == "premium_plus" else []
    insight = result.insight if plan_tier in {"premium", "premium_plus"} else result.insight
    return {"score": result.score, "level": result.level, "insight": insight, "tips": tips[:2]}


@router.post("/conversation-quality", response_model=ConversationQualityResponse)
def conversation_quality(
    req: ConversationQualityRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    score, status = _conversation_quality_from_messages(req.messages or [])
    try:
        track_event(
            db,
            "conversation_quality_scored",
            user_id=current_user.id,
            payload={"score": int(score), "status": str(status), "message_count": len(req.messages or [])},
        )
    except Exception:
        pass
    return {"score": int(score), "status": str(status)}


@router.post("/coach", response_model=CoachResponse)
async def coach(
    req: CoachRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # Normalize locale (must follow request body; no geo/profile fallback here).
    req.locale = normalize_chat_ai_locale(getattr(req, "locale", None) or "en")

    plan = SubscriptionService().get_active_plan(db, current_user.id)
    plan_tier = plan if plan in {"free", "premium", "premium_plus"} else "free"
    provider_used = "fallback"
    fallback_reason: str | None = None
    health = _conversation_health_heuristic(
        messages=[{"role": m.role, "text": m.text} for m in (req.messages or [])],
        locale=req.locale,
    )

    if settings.ENABLE_AI_SUGGESTIONS:
        provider = get_ai_provider()
        logger.info(
            "ai_request_started",
            extra={
                "endpoint": "coach",
                "ai_provider": getattr(provider, "__class__", type("x", (), {})).__name__.lower(),
                "ai_model": getattr(settings, "GEMINI_CHAT_MODEL", "") or getattr(settings, "GEMINI_MODEL", "") or "",
                "locale": req.locale,
            },
        )

        async def _coach_provider():
            return await _with_timeout(
                provider.dating_coach_guidance([str(m.text or "") for m in (req.messages or [])], locale=req.locale),
                timeout_s=_AI_PROVIDER_TIMEOUT_S,
            )

        async def _coach_provider_fb():
            return None

        out = await safe_ai_generate_async(_coach_provider, _coach_provider_fb, endpoint="coach", locale=req.locale)
        if isinstance(out, dict) and str(out.get("tone") or "").strip():
            provider_used = "gemini" if getattr(provider, "__class__", type("x", (), {})).__name__.lower().startswith("gemini") else "provider"
            msg = str(out.get("ask_next") or "").strip() or str(out.get("tone") or "").strip()
            track_event(db, "ai_request_success", user_id=current_user.id, payload={"endpoint": "coach", "provider_used": provider_used})
            sugg = await _fallback_3_replies_localized((req.messages[-1].text if req.messages else "") or "", locale=req.locale, continue_mode=True)
            if plan_tier == "premium_plus":
                return {
                    "state": "nudge",
                    "message": msg[:420],
                    "actions": [],
                    "health_score": int(health.get("health_score", 50)),
                    "attraction_level": str(health.get("attraction_level", "medium")),
                    "drop_risk": str(health.get("drop_risk", "medium")),
                    "trend": str(health.get("trend", "stable")),
                    "signals": list(health.get("signals") or [])[:10],
                    "diagnosis": str(health.get("diagnosis") or "")[:320],
                    "next_move": str(health.get("next_move") or "")[:220],
                    "next_suggestions": [str(x or "").strip() for x in sugg[:3]],
                    "locale": req.locale,
                    "source": "ai",
                }
            return {
                "state": "nudge",
                "message": msg[:420],
                "actions": [],
                "next_suggestions": [str(x or "").strip() for x in sugg[:3]],
                "locale": req.locale,
                "source": "ai",
            }
        fallback_reason = "empty_provider_output" if isinstance(out, dict) else "provider_failed"

    result = coach_intervention(
        messages=[{"role": m.role, "text": m.text} for m in (req.messages or [])],
        draft=req.draft,
        readiness_score=req.readiness_score,
        plan_tier=plan_tier,
        locale=req.locale,
    )
    if fallback_reason:
        logger.info("ai_fallback_used", extra={"endpoint": "coach", "fallback_reason": fallback_reason, "provider_used": provider_used})
        track_event(db, "ai_fallback_used", user_id=current_user.id, payload={"endpoint": "coach", "reason": fallback_reason})
    if plan_tier == "premium_plus":
        return {
            "state": result.state,
            "message": result.message,
            "actions": [{"type": a.type, "label": a.label} for a in (result.actions or [])][:2],
            "health_score": int(health.get("health_score", 50)),
            "attraction_level": str(health.get("attraction_level", "medium")),
            "drop_risk": str(health.get("drop_risk", "medium")),
            "trend": str(health.get("trend", "stable")),
            "signals": list(health.get("signals") or [])[:10],
            "diagnosis": str(health.get("diagnosis") or "")[:320],
            "next_move": str(health.get("next_move") or "")[:220],
            "next_suggestions": [str(x or "").strip() for x in (health.get("next_suggestions") or [])[:3]],
            "locale": req.locale,
            "source": "fallback",
        }
    return {
        "state": result.state,
        "message": result.message,
        "actions": [{"type": a.type, "label": a.label} for a in (result.actions or [])][:2],
        "next_suggestions": [str(x or "").strip() for x in (health.get("next_suggestions") or [])[:3]],
        "locale": req.locale,
        "source": "fallback",
    }


@router.post("/escalation-readiness", response_model=EscalationReadinessResponse)
def escalation_readiness_endpoint(
    req: EscalationReadinessRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    plan = SubscriptionService().get_active_plan(db, current_user.id)
    plan_tier = plan if plan in {"free", "premium", "premium_plus"} else "free"
    result = escalation_readiness(
        messages=[{"role": m.role, "text": m.text} for m in (req.messages or [])],
        readiness_score=req.readiness_score,
        coach_state=req.coach_state,
        plan_tier=plan_tier,
        locale=req.locale,
    )
    return {
        "voice_ready": result.voice_ready,
        "video_ready": result.video_ready,
        "date_ready": result.date_ready,
        "primary_step": result.primary_step,
        "confidence": result.confidence,
        "message": result.message,
    }


@router.post("/recovery", response_model=RecoveryResponse)
def recovery_endpoint(
    req: RecoveryRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    plan = SubscriptionService().get_active_plan(db, current_user.id)
    plan_tier = plan if plan in {"free", "premium", "premium_plus"} else "free"
    result = recovery_intervention(
        messages=[{"role": m.role, "text": m.text} for m in (req.messages or [])],
        last_message_age_minutes=req.last_message_age_minutes,
        readiness_score=req.readiness_score,
        coach_state=req.coach_state,
        plan_tier=plan_tier,
        locale=req.locale,
    )
    return {"state": result.state, "message": result.message, "suggestions": (result.suggestions or [])[:3]}


def _get_profile_by_id_or_user_id(db: Session, raw_id: int) -> Profile | None:
    # Backward/interop-friendly: if callers pass a user_id, fall back to lookup by Profile.user_id.
    p = db.query(Profile).filter(Profile.id == raw_id).first()
    if p:
        return p
    return db.query(Profile).filter(Profile.user_id == raw_id).first()


@router.post("/compatibility-score", response_model=CompatibilityScoreResponse)
def compatibility_score(
    req: CompatibilityScoreRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # Always use the authenticated user's plan tier (not the request).
    plan = SubscriptionService().get_active_plan(db, current_user.id)
    plan_tier = plan if plan in {"free", "premium", "premium_plus"} else "free"

    viewer = _get_profile_by_id_or_user_id(db, int(req.viewer_profile_id))
    candidate = _get_profile_by_id_or_user_id(db, int(req.candidate_profile_id))
    if not viewer or not candidate:
        # Non-blocking: just return unavailable.
        return {
            "score": 0,
            "level": "low",
            "reasons": [],
            "visual_score": None,
            "vibe_score": None,
            "symmetry_score": None,
            "available": False,
        }

    svc = CompatibilityService()
    result = svc.score_pair(
        viewer=viewer,
        candidate=candidate,
        plan_tier=plan_tier,
        locale=req.locale,
        db=db,
        emit_trust_impact=True,
    )
    return {
        "score": result.score,
        "level": result.level,
        "reasons": result.reasons,
        "visual_score": result.visual_score,
        "vibe_score": result.vibe_score,
        "symmetry_score": result.symmetry_score,
        "available": bool(result.available),
    }


@router.post("/compatibility-score/batch", response_model=CompatibilityScoreBatchResponse)
def compatibility_score_batch(
    req: CompatibilityScoreBatchRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    plan = SubscriptionService().get_active_plan(db, current_user.id)
    plan_tier = plan if plan in {"free", "premium", "premium_plus"} else "free"

    viewer = _get_profile_by_id_or_user_id(db, int(req.viewer_profile_id))
    if not viewer:
        return {"results": []}

    ids = [int(x) for x in (req.candidate_profile_ids or []) if isinstance(x, int) or str(x).isdigit()]
    ids = [x for x in ids if x > 0][:25]
    if not ids:
        return {"results": []}

    svc = CompatibilityService()
    out = []
    for cid in ids:
        cand = _get_profile_by_id_or_user_id(db, cid)
        if not cand:
            out.append(
                {
                    "candidate_profile_id": cid,
                    "score": 0,
                    "level": "low",
                    "reasons": [],
                    "visual_score": None,
                    "vibe_score": None,
                    "symmetry_score": None,
                    "available": False,
                }
            )
            continue
        r = svc.score_pair(viewer=viewer, candidate=cand, plan_tier=plan_tier, locale=req.locale, db=db, emit_trust_impact=False)
        out.append(
            {
                "candidate_profile_id": cid,
                "score": r.score,
                "level": r.level,
                "reasons": r.reasons,
                "visual_score": r.visual_score,
                "vibe_score": r.vibe_score,
                "symmetry_score": r.symmetry_score,
                "available": bool(r.available),
            }
        )
    return {"results": out}


@router.post("/improve-reply")
async def wingman_improve_reply(
    req: ImproveReplyRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    raw_ui = getattr(req, "locale", None)
    req.locale = _resolve_ai_locale_for_request(
        req_locale=raw_ui,
        ai_locale=getattr(req, "ai_locale", None),
        request=request,
        db=db,
        current_user=current_user,
        latest_user_message=req.draft,
        prefer_message_locale=False,
        route_label="POST /ai/improve-reply",
    )
    log_ai_locale_context(logger, endpoint="improve-reply", ui_locale=raw_ui, ai_locale=req.locale)
    logger.info("AI locale used: %s", req.locale)

    try:
        plan_tier, _ = enforce_and_consume_ai_usage(db, user_id=int(current_user.id), usage_type="improve")
    except AiNotUnlocked:
        _raise_ai_unlock_after_match()
    except AiLimitReached:
        _raise_ai_limit_hit()
    except AiRapidCooldown:
        plan_tier = "free"
    premium = plan_tier in {"premium", "premium_plus"}
    plus = plan_tier == "premium_plus"
    plan = plan_tier
    _lim = message_context_limit(plan_tier)
    _cc = [str(x or "").strip() for x in (req.conversation_context or []) if str(x or "").strip()]
    req.conversation_context = _cc[-_lim:]

    def _local_variants() -> list[dict]:
        rows = improve_draft_locally(
            req.draft,
            req.conversation_context,
            req.user_style,
            allow_edgy_mode=req.allow_edgy_mode,
            locale=req.locale,
        )
        return [{"text": x["text"], "style": x["style"]} for x in rows[:3]]

    if not settings.ENABLE_AI_SUGGESTIONS:
        local = _local_variants()
        safe_texts = filter_chat_suggestions(kind="rewrite", candidates=[str(x.get("text") or "") for x in local])
        return {
            "variants": [{"text": x.text, "style": "safe", "safety_flags": x.flags} for x in safe_texts],
            "meta": {"limited": True, "source": "fallback", "locale": req.locale},
        }
    try:
        if plan_tier == "free" and bool(getattr(settings, "AI_STRICT_MONETIZATION", False)) and not bool(os.getenv("PYTEST_CURRENT_TEST")):
            local = _local_variants()
            safe_texts = filter_chat_suggestions(kind="rewrite", candidates=[str(x.get("text") or "") for x in local])
            return {
                "variants": [{"text": x.text, "style": "safe", "safety_flags": x.flags} for x in safe_texts],
                "meta": {"limited": False, "source": "fallback", "locale": req.locale},
            }
        enforce_ai_limits(db, current_user.id)
    except RateLimitExceeded:
        local = _local_variants()
        safe_texts = filter_chat_suggestions(kind="rewrite", candidates=[str(x.get("text") or "") for x in local])
        return {
            "variants": [{"text": x.text, "style": "safe", "safety_flags": x.flags} for x in safe_texts],
            "meta": {"limited": True, "source": "fallback", "locale": req.locale},
        }
    trust_bucket, viewer_is_verified, viewer_is_low_quality = _viewer_trust_bucket(db, current_user.id)
    _rewrite_mode_union = _FREE_REWRITE_MODES | _PREMIUM_REWRITE_MODES
    requested_mode = _normalize_improve_reply_mode(req.mode)
    effective_mode = requested_mode
    if plan_tier == "free" and effective_mode not in _FREE_REWRITE_MODES:
        effective_mode = "polish"
    if effective_mode not in _rewrite_mode_union:
        effective_mode = "polish"
    track_event(
        db,
        "ai_chat_rewrite_requested",
        user_id=current_user.id,
        payload={
            "mode": requested_mode,
            "premium": premium,
            "plan": plan,
            "ctx_len": len(req.conversation_context or []),
            "draft_len": len(req.draft or ""),
        },
    )
    policy = _get_ai_style_policy(
        plan_tier=plan_tier,
        is_verified=viewer_is_verified,
        is_low_quality=viewer_is_low_quality,
        requested_mode=effective_mode,
    )
    effective_mode = str(policy.get("effective_mode") or effective_mode)
    if plan_tier == "free" and effective_mode not in _FREE_REWRITE_MODES:
        effective_mode = "polish"
    req.mode = effective_mode
    # Low-quality viewers: clamp edgy mode regardless of request.
    if viewer_is_low_quality:
        req.allow_edgy_mode = False

    from app.services.ai.orchestrator import AIOrchestrator

    try:
        variants = await AIOrchestrator.run_improve_reply_core(
            draft=req.draft,
            conversation_context=req.conversation_context or [],
            user_style=req.user_style,
            allow_edgy_mode=req.allow_edgy_mode,
            mode=str(req.mode or "polish"),
            plan_tier=plan_tier,
            locale=req.locale,
            timeout_s=_AI_PROVIDER_TIMEOUT_S,
        )
    except Exception as e:
        local = _local_variants()
        safe_texts = filter_chat_suggestions(kind="rewrite", candidates=[str(x.get("text") or "") for x in local])
        fallback_reason = "timeout" if isinstance(e, asyncio.TimeoutError) else "gemini_error"
        logger.info(
            "chat_ai_fallback_used",
            extra={"endpoint": "improve-reply", "reason": fallback_reason, "locale": req.locale, "detail": str(e)[:160]},
        )
        return {
            "variants": [{"text": x.text, "style": "safe", "safety_flags": x.flags} for x in safe_texts],
            "meta": {"limited": True, "source": "fallback", "locale": req.locale, "provider_failed_reason": str(e)[:120]},
        }
    logger.info(
        "ai_assist_rewrite served",
        extra={
            "provider_used": "use_case",
            "fallback_reason": None,
            "trust_bucket": trust_bucket,
            "requested_mode": requested_mode,
            "effective_mode": effective_mode,
            "plan_tier": plan_tier,
            "ctx_len": len(req.conversation_context or []),
            "draft_len": len(req.draft or ""),
        },
    )
    mode = (req.mode or "").strip().lower()
    style_key = mode if mode else "polish"
    # Local/provider variants now may include a richer set of style keys.
    priority_by_mode: dict[str, dict[str, int]] = {
        "polish": {"polish": 0, "safe": 1, "more_natural": 2, "shorter": 3},
        "natural": {"more_natural": 0, "engaging": 1, "safe": 2, "polish": 3},
        "shorter": {"shorter": 0, "polish": 1, "safe": 2},
        # Premium Plus modes (best-effort ordering)
        "flirty": {"flirty": 0, "tease_lightly": 1, "more_natural": 2, "polish": 3},
        "witty": {"witty": 0, "tease_lightly": 1, "polish": 2},
        "charming": {"more_natural": 0, "polish": 1},
        "direct": {"direct": 0, "polish": 1, "shorter": 2},
        "thoughtful": {"thoughtful": 0, "more_natural": 1, "polish": 2},
        "tease_lightly": {"tease_lightly": 0, "witty": 1, "polish": 2},
        "more_natural": {"more_natural": 0, "engaging": 1, "safe": 2, "polish": 3},
        "confident": {"slightly_bold": 0, "engaging": 1, "safe": 2, "polish": 3},
        "softer": {"safe": 0, "more_natural": 1, "engaging": 2},
        "romantic": {"engaging": 0, "more_natural": 1, "safe": 2},
        "deep": {"thoughtful": 0, "more_natural": 1, "safe": 2},
        "playful": {"witty": 0, "tease_lightly": 1, "engaging": 2},
    }
    priority = priority_by_mode.get(style_key)
    if priority:
        variants = sorted(variants, key=lambda v: priority.get(str(v.get("style") or ""), 99))
    safe_texts = filter_chat_suggestions(kind="rewrite", candidates=[str(x.get("text") or "") for x in (variants or [])])
    fixed_texts = await _enforce_ai_texts_locale_once([str(x.text or "") for x in safe_texts], locale=req.locale)
    if fixed_texts:
        class _SafeRow:
            def __init__(self, text: str, flags: list[str]):
                self.text = text
                self.flags = flags

        safe_texts = [
            _SafeRow(fixed_texts[i] if i < len(fixed_texts) else str(x.text or ""), list(getattr(x, "flags", []) or []))
            for i, x in enumerate(safe_texts)
        ]
    polished_rows = [polish_reply_quality(x.text, locale=req.locale, max_len=220) for x in safe_texts]
    return {
        "variants": [
            ({
                "text": row["text"],
                "style": str((variants[i].get("style") if i < len(variants) else "safe") or "safe"),
                "safety_flags": sorted(set(list(safe_texts[i].flags) + list(row["quality_flags"]))),
                "quality_score": row["quality_score"],
                "quality_flags": row["quality_flags"],
            } | _reply_question_tone(
                text=row["text"],
                tone=str((variants[i].get("style") if i < len(variants) else "playful") or "playful"),
            ))
            for i, row in enumerate(polished_rows)
        ],
        "meta": {"limited": False, "source": "ai", "locale": req.locale, "quality": [{"quality_score": r["quality_score"], "quality_flags": r["quality_flags"]} for r in polished_rows]},
    }


@router.post("/next-step")
async def wingman_next_step(
    req: NextStepRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Return 3 actionable “next step” options (voice/date/video).
    Never auto-sent; UI must require a tap.
    """
    # Backward compatibility: older clients may send {"analysis": {...}}.
    analysis = getattr(req, "analysis", None)
    if isinstance(analysis, dict) and analysis:
        if not settings.ENABLE_AI_SUGGESTIONS:
            return {"next_step": {}}
        try:
            enforce_ai_limits(db, current_user.id)
        except RateLimitExceeded:
            return {"next_step": {}}
        return {"next_step": await suggest_next_step(req.analysis)}

    # New contract: allow a minimal request body (no analysis) and return list[options].
    # We keep this deterministic + safe (no pressure, no personal data).
    loc = "en"
    try:
        from app.services.app_language import normalize_app_language

        loc = normalize_app_language(getattr(req, "locale", None) or "en")  # type: ignore[attr-defined]
    except Exception:
        loc = "en"
    if loc not in {"en", "uk", "ru"}:
        loc = "en"

    def _opt(typ: str, text: str) -> dict:
        return {"type": typ, "text": text}

    if loc == "ru":
        opts = [
            _opt("voice", "Хочешь, я запишу короткое голосовое? 🙂"),
            _opt("date", "Есть идея: кофе на этой неделе — какой день тебе удобнее?"),
            _opt("video", "Если тебе ок, можем созвониться на 5 минут сегодня вечером?"),
        ]
    elif loc == "uk":
        opts = [
            _opt("voice", "Хочеш, я запишу коротке голосове? 🙂"),
            _opt("date", "Є ідея: кава цього тижня — який день тобі зручний?"),
            _opt("video", "Якщо тобі ок, можемо зідзвонитися на 5 хвилин сьогодні ввечері?"),
        ]
    else:
        opts = [
            _opt("voice", "Want me to send a quick voice note? 🙂"),
            _opt("date", "Low‑key idea: coffee this week — what day works for you?"),
            _opt("video", "If you’re up for it, want to do a 5‑minute call later today?"),
        ]

    return opts
