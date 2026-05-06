"""
In-chat AI suggestion packs (light / flirty / deep) for matched users only.
Uses recent thread text on the server for the requesting user — never exposed to admins.
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.models.message import Message
from app.models.profile import Profile
from app.services.ai.gemini_client import GeminiClient
from app.services.ai.safe_ai import safe_ai_generate_async
from app.services.ai.safety.chat_safety import filter_chat_suggestions
from app.services.ai.chat_brain_style_profile import (
    build_style_prompt_hint,
    deep_extra_risk_from_profile,
    get_chat_brain_style_profile,
    score_boost_from_profile,
    style_public_summary,
)
from app.services.ai.ai_request_locale import normalize_chat_ai_locale
from app.services.ai.locale import is_text_locale
from app.services.ai.ai_output_validation import pack_question_quota_met, validate_chat_brain_line
from app.services.ai.topic_brain import (
    TOPIC_CONFIDENCE_LOW_THRESHOLD,
    detect_conversation_topic,
    topic_anchor_line,
    topic_context_for_prompt,
    topic_fallback_variant,
)
from app.services.ai.conversation.conversation_stage_engine import (
    detect_stage,
    stage_prompt_hint,
    stage_ui_hints,
)
from app.services.ai.conversation.dating_strategy_engine import (
    dating_strategy_prompt_block,
    plan_dating_strategy,
)
from app.services.ai.conversation_coach import assess_conversation, polish_reply_quality
from app.services.ai.memory import personalization_prompt_suffix
from app.services.ai.plan_limits import message_context_limit
from app.services.ai.conversation_goal_engine import (
    compute_conversation_goal_state,
    goal_state_prompt_block,
    premium_plus_goal_metrics_public,
)
from app.services.ai.tier_prompting import capability_prompt_block
from app.services.demo_mode import is_demo_user_id
from app.services.analytics import track_event
from app.core.config import settings

log = logging.getLogger("neyra.chat_brain")

ChatBrainMode = Literal["opener", "reply", "revive", "deepen", "flirty"]


class ChatBrainRequest(BaseModel):
    partner_user_id: int = Field(..., ge=1)
    mode: str = "auto"
    tone: str = "auto"
    language: str = "en"
    ai_locale: str | None = Field(default=None, max_length=24)
    language_hint: str | None = Field(default=None, max_length=96)
    """Dating strategist mode: easy | flirty | witty | deep | confident | romantic | playful | premium_pickup_master"""
    conversation_mode: str = "easy"
    regenerate_variant: Literal["light", "flirty", "deep"] | None = None
    peer_variants: dict[str, str] | None = None


class _TonePackOut(BaseModel):
    model_config = {"extra": "ignore"}

    light: str = ""
    flirty: str = ""
    deep: str = ""


class _SingleLineOut(BaseModel):
    model_config = {"extra": "ignore"}

    message: str = ""


def _norm_lang(code: str) -> str:
    return normalize_chat_ai_locale(code)


def _display_name(db: Session, uid: int) -> str:
    p = db.query(Profile).filter(Profile.user_id == int(uid)).first()
    return str(getattr(p, "display_name", "") or "").strip() or "friend"


def _transcript_limit(plan_tier: str) -> int:
    return message_context_limit(plan_tier)


def _normalize_conversation_mode(raw: str, plan_tier: str) -> str:
    tier = (plan_tier or "free").strip().lower()
    if tier not in {"premium", "premium_plus"}:
        return "easy"
    m = (raw or "easy").strip().lower()
    allowed = {
        "easy",
        "flirty",
        "witty",
        "deep",
        "confident",
        "romantic",
        "playful",
        "premium_pickup_master",
    }
    if m not in allowed:
        m = "easy"
    if m == "premium_pickup_master" and tier not in {"premium", "premium_plus"}:
        m = "confident"
    if m == "witty":
        m = "playful"
    return m


def _conversation_mode_instruction(mode: str) -> str:
    mapping = {
        "easy": "CONVERSATION_MODE: Easy — warm, low-pressure, one clear hook; sounds human.",
        "flirty": "CONVERSATION_MODE: Flirty — playful tension, respectful, consent-forward; still specific to transcript.",
        "playful": "CONVERSATION_MODE: Playful / witty — clever, light tease, never mean; invite a reply.",
        "deep": "CONVERSATION_MODE: Deep — thoughtful but early-dating safe; one sincere question.",
        "confident": "CONVERSATION_MODE: Confident — direct, calm energy; no arrogance; still kind.",
        "romantic": "CONVERSATION_MODE: Romantic — soft, specific compliments tied to what they said; not over the top.",
        "premium_pickup_master": (
            "CONVERSATION_MODE: Pickup master — sharp, confident, never cringe: short natural lines, slightly bold, "
            "specific to the transcript, emotionally intelligent. No performative pickup clichés, no negging, "
            "no sexual pressure, no manipulation."
        ),
    }
    return mapping.get(mode, mapping["easy"]) + "\n"


def _basic_topic_context(meta: dict[str, Any], locale: str) -> str:
    topic = str(meta.get("topic") or "general")
    conf = float(meta.get("confidence") or 0)
    hook = ""
    if conf < TOPIC_CONFIDENCE_LOW_THRESHOLD:
        loc = "uk" if normalize_chat_ai_locale(locale) == "uk" else "en"
        hook = f"- low_confidence_opener_seed (translate, do not copy): {topic_anchor_line(topic, 'opener', loc)}\n"
    return (
        "BASIC_TOPIC: use the thread naturally; keep tone warm and human (free tier); avoid dead-end replies.\n"
        f"- detected_topic: {topic} (confidence ~{conf})\n"
        + hook
        + f"- locale: {locale}\n"
    )


def _demo_brain_hook_suffix(db: Session, user_id: int, transcript_lines: list[tuple[str, str]]) -> str:
    if not is_demo_user_id(db, int(user_id)):
        return ""
    n_demo = sum(1 for role, _ in transcript_lines if role == "me")
    hooks = [
        "DEMO_STRATEGY_1: Warm + curious; easy question back.",
        "DEMO_STRATEGY_2: Playful hook; fun binary choice.",
        "DEMO_STRATEGY_3: Expand their topic; show real interest.",
        "DEMO_STRATEGY_4: One small personal detail (stay in character).",
        "DEMO_STRATEGY_5: Invite slightly deeper or lightly flirty direction; respectful.",
    ]
    idx = min(max(n_demo, 0), 4)
    return (
        hooks[idx]
        + "\nYou are replying as the matched user in a dating app. Never say you are AI/demo. "
        "1–2 sentences. Do not agree blindly — react naturally. Vary wording vs earlier messages.\n"
    )


def _transcript_text_history(transcript_lines: list[tuple[str, str]]) -> list[str]:
    return [t for _, t in transcript_lines if (t or "").strip()]


def _load_transcript(db: Session, me: int, partner: int, limit: int = 10) -> list[tuple[str, str]]:
    rows = (
        db.query(Message)
        .filter(
            or_(
                and_(Message.sender_id == me, Message.receiver_id == partner),
                and_(Message.sender_id == partner, Message.receiver_id == me),
            )
        )
        .order_by(Message.created_at.desc())
        .limit(limit)
        .all()
    )
    rows = list(reversed(rows))
    out: list[tuple[str, str]] = []
    for m in rows:
        text = (m.content or "").strip()
        if not text:
            continue
        role = "me" if int(m.sender_id) == int(me) else "partner"
        out.append((role, text[:300]))
    return out


def _load_transcript_with_times(db: Session, me: int, partner: int, limit: int = 60) -> list[dict[str, Any]]:
    """Chronological text messages with timestamps for relationship-stage heuristics."""
    rows = (
        db.query(Message)
        .filter(
            or_(
                and_(Message.sender_id == me, Message.receiver_id == partner),
                and_(Message.sender_id == partner, Message.receiver_id == me),
            )
        )
        .order_by(Message.created_at.desc())
        .limit(limit)
        .all()
    )
    rows = list(reversed(rows))
    out: list[dict[str, Any]] = []
    for m in rows:
        text = (m.content or "").strip()
        if not text:
            continue
        role = "me" if int(m.sender_id) == int(me) else "partner"
        out.append({"role": role, "text": text[:300], "created_at": m.created_at})
    return out


def _transcript_block(lines: list[tuple[str, str]]) -> str:
    if not lines:
        return "(no text messages yet — voice-only lines omitted)"
    parts = []
    for role, text in lines:
        label = "Me" if role == "me" else "Partner"
        parts.append(f"{label}: {text}")
    return "\n".join(parts)


def _mode_instruction(mode: str) -> str:
    m = (mode or "opener").strip().lower()
    mapping = {
        "opener": (
            "Suggest friendly ways to start or restart the chat (new topic ok). "
            "Each line should invite a reply — avoid dead-end statements with nothing to answer."
        ),
        "reply": (
            "Reply naturally to the partner's LATEST message; acknowledge specifics they said. "
            "Move the conversation forward: prefer ending with a light question or clear hook they can answer. "
            "Avoid generic closers that stall the chat."
        ),
        "revive": (
            "The chat slowed or went quiet — you are a conversation coach. "
            "Produce: (1) light: one clear, easy question that re-opens the thread; "
            "(2) flirty: one playful, warm line that still invites a response (no guilt, no 'why did you disappear'); "
            "(3) deep: one thoughtful angle only if it still feels low-pressure. "
            "Never shame the partner for slow replies."
        ),
        "deepen": (
            "Suggest slightly deeper, thoughtful prompts (early-dating appropriate). "
            "Still avoid dead ends — give the partner something concrete to react to."
        ),
        "flirty": (
            "Keep all three playful and warm; stay respectful and consent-forward (no explicit content). "
            "Playfulness should still invite a reply, not perform monologue."
        ),
    }
    return mapping.get(m, mapping["opener"])


def _coach_goals_block() -> str:
    return (
        "CONVERSATION COACH RULES (apply to all three variants):\n"
        "- Primary goals: keep the chat alive, encourage a reply, avoid dead-end messages.\n"
        "- Prefer lines that give the partner something easy to respond to (question, choice, or specific hook).\n"
        "- Do not use guilt, pressure, or manipulation; no sexual pressure or obligation.\n"
        "- Do NOT sound like an AI assistant. Avoid generic 'assistant-y' phrases like: "
        "\"Цікаве порівняння\", \"Мабуть, і те, і інше\", \"Як штучний інтелект...\", \"Я не можу...\".\n"
        "- Prefer natural dating-chat voice: short, slightly playful, informal, human.\n"
        "- Each variant must be meaningfully different (not rephrases of the same idea); do not repeat the same "
        "opening clause or stock phrase across variants.\n"
    )


def _partner_last_text(transcript_lines: list[tuple[str, str]]) -> str:
    for role, text in reversed(transcript_lines or []):
        if role == "partner":
            return str(text or "").strip()
    return ""


def _suggest_say_simple(ctx: dict[str, Any], transcript_lines: list[tuple[str, str]]) -> bool:
    if str(ctx.get("last_text_role") or "") != "partner":
        return False
    last = _partner_last_text(transcript_lines)
    if not last:
        return False
    words = len(last.split())
    return len(last) > 95 or (words > 22 and "?" in last)


def _slow_shallow_thread(transcript_lines: list[tuple[str, str]]) -> bool:
    """Several very short partner turns — conversation may feel stuck."""
    partner_recent = [t for r, t in transcript_lines[-6:] if r == "partner"]
    if len(partner_recent) < 2:
        return False
    short = sum(1 for t in partner_recent if len((t or "").strip()) < 18)
    return short >= 2


def _engagement_momentum(transcript_lines: list[tuple[str, str]]) -> float:
    """0..1 rough score: back-and-forth with substance."""
    recent = transcript_lines[-10:]
    if len(recent) < 4:
        return 0.0
    me_sub = sum(1 for r, t in recent if r == "me" and len((t or "").strip()) > 14)
    them_sub = sum(1 for r, t in recent if r == "partner" and len((t or "").strip()) > 14)
    return min(1.0, (me_sub + them_sub) / 8.0)


def _extra_user_coach_block(
    *,
    effective_mode: str,
    ctx: dict[str, Any],
    transcript_lines: list[tuple[str, str]],
    lang: str,
) -> str:
    parts: list[str] = []
    if _slow_shallow_thread(transcript_lines):
        parts.append(
            "CONTEXT: Partner has sent several very short replies — use a concrete, easy question (light) "
            "or a playful nudge (flirty) to reopen flow; avoid sounding interview-like."
        )
    if effective_mode == "revive" or (ctx.get("hours_since_last_text") is not None and float(ctx.get("hours_since_last_text") or 0) > 12):
        parts.append(
            "CONTEXT: Timing is softer — prioritize curiosity and playfulness over intensity; "
            "at least one variant should end with a simple question."
        )
    if _suggest_say_simple(ctx, transcript_lines):
        parts.append(
            "CONTEXT: Partner's last message is long or complex — the LIGHT variant should be noticeably simple, "
            "warm, and very easy to answer (one short idea + optional tiny question)."
        )
    if not parts:
        return ""
    return "\n".join(parts) + "\n"


def _safe_pack(raw: dict[str, str], partner_name: str | None) -> dict[str, str]:
    out: dict[str, str] = {}
    for key in ("light", "flirty", "deep"):
        text = str(raw.get(key) or "").strip()
        if not text:
            continue
        # Guardrail: avoid "assistant-y" boilerplate that feels unnatural in dating chat.
        low = text.lower()
        if any(x in low for x in ("цікаве порівняння", "мабуть, і те, і інше", "як штучний інтелект", "як ai", "як чат", "як chatgpt")):
            continue
        rows = filter_chat_suggestions(kind="openers", candidates=[text], partner_name=partner_name, max_len=200)
        if rows:
            out[key] = rows[0].text
    return out


async def _repair_variation(
    *,
    transcript: str,
    mode: str,
    lang: str,
    me_name: str,
    partner_name: str,
    variants: dict[str, str],
    style_hint: str = "",
    coach_user_suffix: str = "",
    language_hint: str | None = None,
) -> dict[str, str]:
    """
    Best-effort diversity repair:
    If variants are near-duplicates, regenerate one variant to be semantically different.
    """
    if not GeminiClient.enabled():
        return variants

    v = {k: str(variants.get(k) or "").strip() for k in ("light", "flirty", "deep")}
    pairs = [("light", "flirty"), ("light", "deep"), ("flirty", "deep")]
    max_pair = ("", "", 0.0)
    for a, b in pairs:
        if not v[a] or not v[b]:
            continue
        sim = _word_jaccard(v[a], v[b])
        if sim > max_pair[2]:
            max_pair = (a, b, sim)
    if max_pair[2] < 0.70:
        return variants

    # Single Gemini call policy: no extra provider round-trips for diversity repair.
    return variants


def _fallback_pack(
    mode: str,
    partner_name: str,
    lang: str,
    *,
    last_partner_message: str | None = None,
) -> dict[str, str]:
    name = (partner_name or "").strip() or ("тут" if lang == "uk" else "там" if lang == "ru" else "there")
    lm = " ".join((last_partner_message or "").strip().split())
    mode_key = (mode or "opener").strip().lower()

    if lang == "uk":
        from app.services.ai.conversation.contextual_fallback_triples import (
            uk_chat_brain_overlay,
            uk_reply_fallback_three_lines,
        )

        ov = uk_chat_brain_overlay(str(mode or "auto"), lm or None)
        if ov:
            return ov
        if lm and mode_key in {"reply", "auto", "deepen", "flirty"}:
            trip = uk_reply_fallback_three_lines(lm, continue_mode=True)
            return {"light": trip[0], "flirty": trip[1], "deep": trip[2]}
    if lang == "uk":
        packs = {
            "opener": (
                f"Привіт! {name} — якщо ок, розкажеш одне цікаве про свій день?",
                f"Схоже, нам є про що поговорити — що б ти хотів(ла) зробити в ідеальні вихідні?",
                f"Якщо коротко: що для тебе зараз важливіше — спокій чи нові враження?",
            ),
            "reply": (
                "Це класно чути — а що з цього тобі найбільше зайшло?",
                "Мені подобається твій настрій у цьому. Розкажеш трохи більше?",
                "Звучить цікаво. Якби ти міг(ла) продовжити в один крок — що б це було?",
            ),
            "revive": (
                "Привіт знову — якщо ще актуально, хочеш коротко продовжити?",
                "Повертаюсь з легким пінгом: якщо хочеш, можемо вибрати одну тему на сьогодні.",
                "Без тиску — якщо тобі зручно, давай підхопимо розмову з маленького питання.",
            ),
            "deepen": (
                "Що для тебе зараз означає «хороші стосунки» на старті?",
                "Як ти зазвичай розумієш, що людині можна довіряти в чаті?",
                "Яка річ у знайомствах тебе найбільше хвилює — і що тебе заспокоює?",
            ),
            "flirty": (
                f"Окей, {name}, чесно: ти вже вигадуєш, про що написати, чи це тільки я? 😉",
                "Здається, у нас добрий матч — готовий(а) перевірити це в повідомленнях?",
                "Якщо це не занадто швидко: що тебе найбільше інтригує в людях онлайн?",
            ),
        }
    elif lang == "ru":
        packs = {
            "opener": (
                f"Привет! {name} — что было самым классным в твоей неделе?",
                "Мы совпали — если хочешь, что тебя сейчас по-настоящему радует?",
                "Если бы на этих выходных можно было сделать одну вещь, что бы ты выбрал(а)?",
            ),
            "reply": (
                "Классно. А что в этом тебе зашло сильнее всего?",
                "Мне нравится твой вайб. Расскажешь чуть больше?",
                "Звучит интересно. Если продолжить одним шагом — что бы это было?",
            ),
            "revive": (
                "Привет ещё раз — без давления: хочешь легко продолжить?",
                "Лёгкий пинг: можем начать заново с одной простой темы.",
                "Если тебе ок, давай подхватим разговор с маленького вопроса 🙂",
            ),
            "deepen": (
                "Что для тебя сейчас значит «здоровые отношения» на старте?",
                "Как ты обычно понимаешь, что человеку можно доверять в переписке?",
                "Что в знакомствах тебя больше всего волнует — и что помогает расслабиться?",
            ),
            "flirty": (
                f"Окей, {name}, честно: ты тоже сейчас придумываешь, что написать, или это только я? 😉",
                "Кажется, у нас хороший мэтч — проверим химию в одном сообщении?",
                "Если не слишком смело: что тебя больше всего цепляет в том, как человек пишет?",
            ),
        }
    elif lang == "pt":
        packs = {
            "opener": (
                f"Oi! {name} — rapidinho: qual foi a melhor parte da sua semana até agora?",
                "A gente deu match — se você topar, qual é uma coisinha que te anima ultimamente?",
                "Se você pudesse fazer uma coisa legal no fim de semana, o que seria?",
            ),
            "reply": (
                "Que legal. O que disso foi mais importante pra você?",
                "Curti sua energia. Quer me contar um pouco mais?",
                "Interessante — se fosse continuar com um passo pequeno, qual seria?",
            ),
            "revive": (
                "Oi de novo — sem pressão: quer retomar de leve?",
                "Um ping leve: a gente pode recomeçar com um tema simples 🙂",
                "Se for de boa pra você, vamos continuar com uma perguntinha?",
            ),
            "deepen": (
                "O que significa pra você um “relacionamento saudável” no começo?",
                "Como você percebe que dá pra confiar em alguém conversando por mensagem?",
                "O que mais te preocupa em conhecer alguém — e o que te acalma?",
            ),
            "flirty": (
                f"Ok, {name}, sinceramente: você também tá pensando no que escrever ou só eu? 😉",
                "Acho que a gente combina — bora testar a química numa mensagem?",
                "Se não for ousado demais: o que mais te chama atenção no jeito que alguém conversa?",
            ),
        }
    elif lang == "es":
        packs = {
            "opener": (
                f"¡Hola! {name} — rápido: ¿qué fue lo mejor de tu semana hasta ahora?",
                "Hicimos match — si te apetece, ¿qué cosita te ilusiona últimamente?",
                "Si este finde pudieras hacer una cosa divertida, ¿qué elegirías?",
            ),
            "reply": (
                "Qué bien. ¿Qué parte de eso fue lo más importante para ti?",
                "Me gusta tu vibra. ¿Me cuentas un poco más?",
                "Interesante — si lo siguieras con un paso pequeño, ¿cuál sería?",
            ),
            "revive": (
                "Hola de nuevo — sin presión: ¿retomamos suave?",
                "Un ping ligero: podemos empezar de nuevo con un tema simple 🙂",
                "Si te va bien, sigamos con una preguntita.",
            ),
            "deepen": (
                "¿Qué significa para ti una “relación sana” al principio?",
                "¿Cómo notas que se puede confiar en alguien por chat?",
                "¿Qué te preocupa más al conocer gente — y qué te tranquiliza?",
            ),
            "flirty": (
                f"Ok, {name}, en serio: ¿tú también estás pensando qué escribir o solo yo? 😉",
                "Creo que hay buena química — ¿la probamos con un mensaje?",
                "Si no es muy atrevido: ¿qué te engancha del estilo de mensajes de alguien?",
            ),
        }
    elif lang == "ja":
        packs = {
            "opener": (
                f"やっほー{name}！今週いちばん良かったことって何？",
                "マッチしたね。最近ちょっとワクワクしてることある？",
                "もし週末に一つだけ楽しいことできるなら、何したい？",
            ),
            "reply": (
                "いいね。そこって一番大事なのはどの部分？",
                "その感じ、好き。もう少し詳しく聞かせて？",
                "興味深いね。小さく一歩進めるなら、次は何がいい？",
            ),
            "revive": (
                "またこんにちは。無理なく、ゆるく続ける？",
                "軽くピン！今日は一つだけ話題決めてみる？",
                "よかったら、ちいさな質問から再開しよ🙂",
            ),
            "deepen": (
                "今のあなたにとって「良い関係」ってどんな感じ？",
                "チャットで「信頼できる」ってどう判断する？",
                "出会いで一番不安なことって何？逆に安心するのは？",
            ),
            "flirty": (
                f"ねぇ{name}、正直に言って…今なに送ろうか考えてた？😉",
                "いい感じのマッチかも。1通で相性チェックしよ？",
                "ちょい大胆だけど…文章のどこに惹かれるタイプ？",
            ),
        }
    elif lang == "en":
        packs = {
            "opener": (
                f"Hey {name} — quick one: what’s been the best part of your week so far?",
                "We matched — if you’re up for it, what’s a small thing you’re excited about lately?",
                "Hi! If you could do one fun thing this weekend, what would it be?",
            ),
            "reply": (
                "That’s cool — what part of that mattered most to you?",
                "I like your energy here. Want to expand on that a bit?",
                "Interesting — if you continued in one tiny step, what would it be?",
            ),
            "revive": (
                "Hey again — no pressure, but if you’re still up for chatting, want to pick it up lightly?",
                "Small ping: if timing was off earlier, we can restart with one easy topic.",
                "If you’re open to it, I’d love to continue — maybe one question to warm it up?",
            ),
            "deepen": (
                "What does ‘healthy early dating’ mean to you right now?",
                "How do you usually tell someone is trustworthy in chat?",
                "What tends to make you nervous in dating — and what helps you feel safe?",
            ),
            "flirty": (
                f"Okay {name} — be honest: are you drafting messages too, or is it just me? 😉",
                "This match feels promising — want to test our chat chemistry with one line?",
                "If it’s not too forward: what’s one thing you find most attractive in how someone texts?",
            ),
        }
    else:
        from app.services.ai.ai_fallback_phrases import compose_chat_brain_packs

        packs = compose_chat_brain_packs(lang)
    m = (mode or "opener").strip().lower()
    if m not in packs:
        m = "opener"
    a, b, c = packs[m]
    return {"light": a, "flirty": b, "deep": c}


def fallback_pack(
    mode: str,
    partner_name: str,
    lang: str,
    *,
    last_partner_message: str | None = None,
) -> dict[str, str]:
    """Public, provider-free fallback pack for API endpoints."""
    return _fallback_pack(mode, partner_name, lang, last_partner_message=last_partner_message)


THREAD_STALE_HOURS = 36
WAIT_HIDE_SEC = 120
WAIT_SOFT_SEC = 600
RISK_LONG_CHARS = 165
SHALLOW_TURNS = 4

ChatBrainRisk = Literal["safe", "neutral", "risky"]
RecoReason = Literal["easy_not_spam", "invites_reply", "fits_context"]
CoachAction = Literal["write_now", "wait", "change_style"]


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


def _load_thread_context(db: Session, me: int, partner: int) -> dict[str, Any]:
    """Lightweight stats for coaching — no message bodies sent outside this service."""
    now = datetime.now(UTC)
    q_base = db.query(Message).filter(
        or_(
            and_(Message.sender_id == me, Message.receiver_id == partner),
            and_(Message.sender_id == partner, Message.receiver_id == me),
        ),
        Message.content.isnot(None),
    )
    text_q = q_base.filter(Message.content != "")
    total_text = int(text_q.count())
    last = text_q.order_by(Message.created_at.desc()).first()
    last_role: str | None = None
    last_at: datetime | None = None
    last_snip = ""
    if last:
        last_role = "me" if int(last.sender_id) == int(me) else "partner"
        last_at = _aware(last.created_at)
        last_snip = str(last.content or "").strip()[:120]
    hours_since = None
    if last_at:
        hours_since = max(0.0, (now - last_at).total_seconds() / 3600.0)
    return {
        "text_count": total_text,
        "last_text_role": last_role,
        "last_text_at": last_at,
        "hours_since_last_text": hours_since,
        "last_snippet": last_snip,
        "now": now,
    }


def _trailing_me_count(lines: list[tuple[str, str]]) -> int:
    n = 0
    for role, _ in reversed(lines):
        if role != "me":
            break
        n += 1
    return n


def _normalize_words(text: str) -> set[str]:
    raw = re.sub(r"[^\w\s\u0400-\u04FF]", " ", (text or "").lower())
    parts = [p for p in raw.split() if len(p) > 2]
    return set(parts)


def _word_jaccard(a: str, b: str) -> float:
    wa, wb = _normalize_words(a), _normalize_words(b)
    if not wa or not wb:
        return 0.0
    inter = len(wa & wb)
    uni = len(wa | wb)
    return float(inter) / float(uni) if uni else 0.0


def _template_score(text: str) -> int:
    t = (text or "").lower()
    needles = (
        "i would love",
        "i'd love",
        "looking forward",
        "hope you are",
        "hope you're",
        "dear ",
        "kind regards",
        "as discussed",
    )
    return sum(1 for n in needles if n in t)


def _resolve_context_mode(ctx: dict[str, Any], transcript_lines: list[tuple[str, str]]) -> str:
    tc = int(ctx.get("text_count") or 0)
    if tc == 0:
        return "opener"
    hours = ctx.get("hours_since_last_text")
    last_role = ctx.get("last_text_role")
    if hours is not None and float(hours) >= float(THREAD_STALE_HOURS):
        return "revive"
    if last_role == "partner":
        return "reply"
    trail = _trailing_me_count(transcript_lines)
    if trail >= 2:
        return "revive"
    if last_role == "me":
        return "reply"
    return "opener"


def _normalize_requested_mode(mode: str) -> str:
    m = (mode or "auto").strip().lower()
    if m == "smart":
        return "auto"
    if m == "deep":
        return "deepen"
    if m in {"opener", "reply", "revive", "deepen", "flirty", "auto"}:
        return m
    return "auto"


def _effective_generation_mode(requested: str, ctx: dict[str, Any], transcript_lines: list[tuple[str, str]]) -> tuple[str, str]:
    """
    Returns (effective_mode, resolution_source) where source is 'auto' or 'user'.
    """
    norm = _normalize_requested_mode(requested)
    if norm == "auto":
        return _resolve_context_mode(ctx, transcript_lines), "auto"
    return norm, "user"


def _visible_modes_for_context(ctx: dict[str, Any]) -> list[str]:
    tc = int(ctx.get("text_count") or 0)
    base = ["smart", "opener", "flirty", "deep"]
    if tc == 0:
        return base
    return ["smart", "opener", "reply", "revive", "flirty", "deep"]


def _coaching_gate(
    ctx: dict[str, Any],
    transcript_lines: list[tuple[str, str]],
    effective_mode: str,
) -> dict[str, Any]:
    """Decide coaching copy + whether to skip LLM for speed / UX."""
    now = ctx.get("now") or datetime.now(UTC)
    last_role = ctx.get("last_text_role")
    last_at: datetime | None = ctx.get("last_text_at")
    trail_me = _trailing_me_count(transcript_lines)
    coaching: dict[str, Any] = {"action": "write_now"}
    ui: dict[str, Any] = {"suggestions_visible": True, "wait_phase": None}
    run_generation = True

    if last_role == "me" and last_at:
        delta = (now - last_at).total_seconds()
        if delta < WAIT_HIDE_SEC:
            run_generation = False
            coaching["action"] = "wait"
            ui["suggestions_visible"] = False
            ui["wait_phase"] = "hard"
        elif delta < WAIT_SOFT_SEC:
            run_generation = False
            coaching["action"] = "wait"
            ui["suggestions_visible"] = False
            ui["wait_phase"] = "soft"

    if run_generation and trail_me >= 2 and last_role == "me":
        coaching["action"] = "change_style"
        coaching["hint_key"] = "double_text"

    return {"coaching": coaching, "ui": ui, "run_generation": run_generation}


def _merge_coach_hints(
    coaching: dict[str, Any],
    ctx: dict[str, Any],
    transcript_lines: list[tuple[str, str]],
    effective_mode: str,
    plan_tier: str,
) -> dict[str, Any]:
    """Layer context hints (hesitation, momentum) without overriding wait/change_style hints."""
    out = dict(coaching)
    skip_flow_hints = out.get("hint_key") == "double_text"
    plan = (plan_tier or "free").strip().lower()

    if out.get("action") == "wait":
        if not skip_flow_hints and _suggest_say_simple(ctx, transcript_lines):
            out["hint_key"] = "say_simple"
        if plan == "free" and int(ctx.get("text_count") or 0) >= 6 and _engagement_momentum(transcript_lines) >= 0.52:
            out["premium_teaser_key"] = "natural"
        return out
    if not skip_flow_hints:
        if _suggest_say_simple(ctx, transcript_lines):
            out["hint_key"] = "say_simple"
        elif effective_mode == "revive" or _slow_shallow_thread(transcript_lines):
            out["hint_key"] = "keep_alive"

    if plan == "free" and int(ctx.get("text_count") or 0) >= 6 and _engagement_momentum(transcript_lines) >= 0.52:
        out["premium_teaser_key"] = "natural"
    return out


def _risk_and_tip(
    text: str,
    variant: str,
    *,
    text_count: int,
    others: dict[str, str],
    style_profile: dict[str, Any] | None = None,
) -> tuple[ChatBrainRisk, str]:
    t = (text or "").strip()
    if not t:
        return "neutral", "fits_context"
    L = len(t)
    max_sim = max((_word_jaccard(t, o) for k, o in others.items() if k != variant and o.strip()), default=0.0)
    risky = False
    if L >= RISK_LONG_CHARS:
        risky = True
    if variant == "deep" and text_count < SHALLOW_TURNS:
        risky = True
    if (
        style_profile
        and variant == "deep"
        and deep_extra_risk_from_profile(style_profile, text_count)
    ):
        risky = True
    if max_sim >= 0.62:
        risky = True
    if _template_score(t) >= 2:
        risky = True

    if risky:
        tip = "feels_template" if max_sim >= 0.62 or _template_score(t) >= 2 else "long_winded" if L >= RISK_LONG_CHARS else "too_intense_early"
        return "risky", tip
    if L <= 110 and variant == "light":
        return "safe", "easy_open"
    if "?" in t or t.endswith("?"):
        return "safe", "asks_back"
    if L <= 130:
        return "neutral", "matches_mood"
    return "neutral", "fits_context"


def _pick_recommended(
    variants: dict[str, str],
    insights: dict[str, dict[str, str]],
    effective_mode: str,
    text_count: int,
    style_profile: dict[str, Any] | None = None,
) -> tuple[str | None, RecoReason]:
    keys = ("light", "flirty", "deep")
    scored: list[tuple[float, str]] = []
    for k in keys:
        txt = (variants.get(k) or "").strip()
        if not txt:
            continue
        ins = insights.get(k) or {}
        risk = ins.get("risk", "neutral")
        penalty = 2.5 if risk == "risky" else 0.8 if risk == "neutral" else 0.0
        score = 3.0 - penalty
        if k == "light":
            score += 1.6 if effective_mode in {"opener", "revive"} else 0.9
            if text_count < SHALLOW_TURNS:
                score += 1.1
        if k == "flirty":
            score += 1.0 if text_count >= 3 and effective_mode != "opener" else 0.2
            if text_count < 2:
                score -= 1.2
        if k == "deep":
            score += 1.3 if text_count >= 6 and effective_mode == "reply" else 0.2
            if text_count < SHALLOW_TURNS:
                score -= 1.4
        if "?" in txt:
            score += 0.35
        if style_profile:
            score += score_boost_from_profile(style_profile, k)
        scored.append((score, k))
    if not scored:
        return None, None
    scored.sort(key=lambda x: (-x[0], x[1]))
    best = scored[0][1]
    bt = (variants.get(best) or "").strip()
    reason: RecoReason = "fits_context"
    if best == "light" and text_count <= 5:
        reason = "easy_not_spam"
    elif "?" in bt:
        reason = "invites_reply"
    else:
        reason = "fits_context"
    return best, reason


def _build_variant_insights(
    variants: dict[str, str],
    text_count: int,
    style_profile: dict[str, Any] | None = None,
) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    for k in ("light", "flirty", "deep"):
        txt = (variants.get(k) or "").strip()
        if not txt:
            continue
        others = {kk: variants.get(kk) or "" for kk in ("light", "flirty", "deep")}
        risk, tip = _risk_and_tip(txt, k, text_count=text_count, others=others, style_profile=style_profile)
        out[k] = {"risk": risk, "tip_key": tip}
    return out


async def _gemini_full_pack(
    *,
    transcript: str,
    mode: str,
    lang: str,
    me_name: str,
    partner_name: str,
    style_hint: str = "",
    coach_user_suffix: str = "",
    language_hint: str | None = None,
) -> _TonePackOut | None:
    if not GeminiClient.enabled():
        return None
    system = (
        "You are NEYRA's dating conversation strategist (wingman) — not a generic chatbot.\n"
        + _coach_goals_block()
        + "DATING_STRATEGIST_RULES:\n"
        "- Answer the partner's last direct question first (if they asked one). Do not ignore it.\n"
        "- After answering, ask ONE short, natural follow-up.\n"
        "- Each suggestion: 1–2 short sentences, natural voice.\n"
        "- Reference the partner's last message when possible.\n"
        "- About 70% of lines should end with a question or a clear, easy hook they can answer.\n"
        "- Never generic interview prompts (avoid 'tell me about your hobbies/interests' templates).\n"
        "Output ONLY valid JSON: "
        '{"light":"","flirty":"","deep":""}.\n'
        "light = friendly/casual, flirty = playful but respectful, deep = thoughtful.\n"
        "Max ~180 characters per field. No sexual content, no harassment, no manipulation.\n"
        "CRITICAL LANGUAGE RULE:\n"
        "- You MUST respond ONLY in the language specified in the user prompt as LANGUAGE.\n"
        "- Do NOT mix languages. Do NOT transliterate. Do NOT include bilingual text.\n"
        "- If you cannot comply, return empty strings for all fields.\n"
        "STRICT: Return all suggestions ONLY in the LANGUAGE below. Do not use English unless LANGUAGE is 'en'.\n"
        "The suggestions are for the user labeled 'Me' in the transcript."
    )
    hint_line = f"\nSTYLE_HINTS (aggregate preferences, no private data): {style_hint}\n" if (style_hint or "").strip() else ""
    lh = (language_hint or "").strip()
    lang_hint_line = f"\nUI_LANGUAGE_LABEL: {lh}\n" if lh else ""
    suffix = (coach_user_suffix or "").strip()
    user = (
        f"LANGUAGE: {lang}\n"
        f"YOU MUST RESPOND ONLY IN {lang}. NO OTHER LANGUAGE.\n"
        f"{lang_hint_line}"
        f"MODE GUIDANCE: {_mode_instruction(mode)}\n"
        f"Me display name: {me_name}\n"
        f"Partner display name: {partner_name}\n"
        f"{hint_line}\n"
        f"{suffix}\n"
        f"RECENT TRANSCRIPT (latest at bottom):\n{transcript}\n\n"
        "Return three candidate messages Me could send next. Slightly favor the user's typical tone from STYLE_HINTS when consistent with MODE."
    )
    async def _tone_gemini() -> _TonePackOut | None:
        client = GeminiClient()
        raw = await client.generate_json(
            system_prompt=system,
            user_prompt=user,
            out_model=_TonePackOut,
            timeout_s=24.0,
            temperature=0.62,
            max_output_tokens=600,
            model=settings.GEMINI_CHAT_MODEL,
            surface="chat-brain",
        )
        return raw if isinstance(raw, _TonePackOut) else None

    async def _tone_fb() -> None:
        return None

    return await safe_ai_generate_async(_tone_gemini, _tone_fb, endpoint="chat-brain/tone_pack", locale=lang)


async def _gemini_one_line(
    *,
    transcript: str,
    mode: str,
    lang: str,
    me_name: str,
    partner_name: str,
    target: str,
    keep_light: str,
    keep_flirty: str,
    keep_deep: str,
    style_hint: str = "",
    coach_user_suffix: str = "",
    language_hint: str | None = None,
) -> str | None:
    if not GeminiClient.enabled():
        return None
    system = (
        "You are NEYRA's conversation coach. "
        + _coach_goals_block()
        + "Output ONLY JSON: {\"message\":\"...\"}.\n"
        "Write ONE replacement chat line for VARIANT in a dating app.\n"
        "Answer the partner's last direct question first (if they asked one). Do not ignore it.\n"
        "Then ask ONE short follow-up.\n"
        "Consent-forward, respectful, max ~170 chars, no sexual content.\n"
        "Prefer a line that invites a reply (question or hook) when appropriate for the VARIANT.\n"
        "CRITICAL LANGUAGE RULE:\n"
        "- You MUST write entirely in the LANGUAGE specified in the user prompt.\n"
        "- Do NOT mix languages. Do NOT include bilingual text.\n"
        "- If you cannot comply, return {\"message\":\"\"}.\n"
        "STRICT: Write ONLY in LANGUAGE below; no English unless LANGUAGE is 'en'.\n"
        "The line is for the user 'Me'."
    )
    hint = f"STYLE_HINTS: {style_hint}\n" if (style_hint or "").strip() else ""
    lh = (language_hint or "").strip()
    lang_hint_line = f"UI_LANGUAGE_LABEL: {lh}\n" if lh else ""
    suffix = (coach_user_suffix or "").strip()
    user = (
        f"LANGUAGE: {lang}\n"
        f"YOU MUST RESPOND ONLY IN {lang}. NO OTHER LANGUAGE.\n"
        f"{lang_hint_line}"
        f"MODE: {mode}\nVARIANT_TO_REPLACE: {target}\n"
        f"Me: {me_name}\nPartner: {partner_name}\n"
        f"{hint}"
        f"{suffix}\n"
        f"Keep other variants as reference (do not copy verbatim):\n"
        f"light: {keep_light}\nflirty: {keep_flirty}\ndeep: {keep_deep}\n\n"
        f"TRANSCRIPT:\n{transcript}\n\n"
        f"Produce a fresh {target} line only."
    )
    async def _one_gemini() -> str | None:
        client = GeminiClient()
        raw = await client.generate_json(
            system_prompt=system,
            user_prompt=user,
            out_model=_SingleLineOut,
            timeout_s=18.0,
            temperature=0.68,
            max_output_tokens=220,
            model=settings.GEMINI_CHAT_MODEL,
            surface="chat-brain",
        )
        if isinstance(raw, _SingleLineOut) and (raw.message or "").strip():
            return str(raw.message).strip()[:500]
        return None

    async def _one_fb() -> None:
        return None

    out_one = await safe_ai_generate_async(_one_gemini, _one_fb, endpoint="chat-brain/one_line", locale=lang)
    if out_one:
        return out_one
    return None


def _enforce_pack_language(pack: dict[str, str], lang: str) -> dict[str, str]:
    """Drop any variant that clearly violates expected language; caller can refill from fallback."""
    out: dict[str, str] = {}
    for k in ("light", "flirty", "deep"):
        t = str(pack.get(k) or "").strip()
        if t and is_text_locale(t, lang):
            out[k] = t
        else:
            out[k] = ""
    return out


def run_chat_brain_suggestions(
    db: Session, *, user_id: int, body: ChatBrainRequest, plan_tier: str = "free"
) -> dict[str, Any]:
    partner_id = int(body.partner_user_id)
    if partner_id == int(user_id):
        return {"ok": False, "error": "invalid_partner", "variants": {}}

    lang = _norm_lang(body.language)
    lang_hint = str(getattr(body, "language_hint", None) or "").strip() or None
    me_name = _display_name(db, user_id)
    partner_name = _display_name(db, partner_id)
    # Profiles are used for direct-question answers + light memory hooks.
    me_profile = db.query(Profile).filter(Profile.user_id == int(user_id)).first()
    partner_profile = db.query(Profile).filter(Profile.user_id == int(partner_id)).first()
    t_limit = _transcript_limit(plan_tier)
    is_premium_tier = (plan_tier or "free").strip().lower() in {"premium", "premium_plus"}
    transcript_lines = _load_transcript(db, user_id, partner_id, limit=t_limit)
    transcript = _transcript_block(transcript_lines)
    ctx = _load_thread_context(db, user_id, partner_id)
    ctx["now"] = datetime.now(UTC)
    topic_meta = detect_conversation_topic(transcript_lines)
    stage_limit = max(t_limit, 60) if is_premium_tier else t_limit
    stage_messages = _load_transcript_with_times(db, user_id, partner_id, limit=stage_limit)
    stage_info = detect_stage(stage_messages)
    suggested_tone, suggested_conv_mode = stage_ui_hints(str(stage_info.get("stage") or "warmup"))
    conv_mode = _normalize_conversation_mode(str(getattr(body, "conversation_mode", "easy") or "easy"), plan_tier)

    requested_raw = (body.mode or "auto").strip().lower()
    effective_mode, mode_resolution = _effective_generation_mode(requested_raw, ctx, transcript_lines)
    if effective_mode not in {"opener", "reply", "revive", "deepen", "flirty"}:
        effective_mode = "opener"

    tc_pre = int(ctx.get("text_count") or 0)
    if tc_pre == 0 and effective_mode in {"reply", "revive"}:
        effective_mode = "opener"

    gate = _coaching_gate(ctx, transcript_lines, effective_mode)
    coaching = gate["coaching"]
    ui = dict(gate["ui"])
    visible_modes = _visible_modes_for_context(ctx)
    trail_me = _trailing_me_count(transcript_lines)
    hrs_raw = ctx.get("hours_since_last_text")
    hours_since_val = float(hrs_raw) if hrs_raw is not None else None
    dating_strategy = plan_dating_strategy(
        stage_info=stage_info,
        stage_messages=stage_messages,
        last_text_role=str(ctx.get("last_text_role") or "").strip() or None,
        hours_since_last_text=hours_since_val,
        run_generation=bool(gate["run_generation"]),
        trail_me=int(trail_me),
    )

    pt_goal = (plan_tier or "free").strip().lower()
    lr_goal = str(ctx.get("last_text_role") or "").strip().lower()
    who_goal_tr: str | None = None
    if lr_goal == "partner":
        who_goal_tr = "them"
    elif lr_goal == "me":
        who_goal_tr = "me"
    nudge_infer_goal: str | None = None
    if effective_mode == "revive":
        nudge_infer_goal = "revive"
    elif effective_mode == "deepen" and hours_since_val is not None and float(hours_since_val) > 12:
        nudge_infer_goal = "reengage"
    conversation_goal_msgs = [{"role": "them" if r == "partner" else "me", "text": t} for r, t in transcript_lines]
    conversation_goal_state = compute_conversation_goal_state(
        conversation_goal_msgs,
        plan_tier=pt_goal,
        locale=lang,
        hours_since_last_message=hours_since_val,
        who_sent_last=who_goal_tr,
        nudge_type=nudge_infer_goal,
        interest_stage=str(stage_info.get("stage") or ""),
        mutuality_score=int(stage_info.get("mutuality_score") or 0) if stage_info.get("mutuality_score") is not None else None,
    )
    conversation_goal_prompt_extra = goal_state_prompt_block(conversation_goal_state)

    regen = body.regenerate_variant
    peer = body.peer_variants if isinstance(body.peer_variants, dict) else {}
    gemini_used = False

    style_prof = get_chat_brain_style_profile(db, user_id)
    style_public = style_public_summary(style_prof)
    style_hint = build_style_prompt_hint(style_prof) if is_premium_tier else ""

    empty_variants = {"light": "", "flirty": "", "deep": ""}
    meta_base: dict[str, Any] = {
        "premium_mode": is_premium_tier,
        "best_ai_mode": (plan_tier or "free").strip().lower() == "premium_plus",
        "mode": effective_mode,
        "requested_mode": requested_raw,
        "mode_resolution": mode_resolution,
        "context_mode": _resolve_context_mode(ctx, transcript_lines),
        "language": lang,
        "regenerate_variant": regen,
        "visible_modes": visible_modes,
        "text_message_count": int(ctx.get("text_count") or 0),
        "style_public": style_public,
        "topic": topic_meta.get("topic"),
        "topic_confidence": topic_meta.get("confidence"),
        "conversation_stage": topic_meta.get("conversation_stage"),
        "emotional_tone": topic_meta.get("emotional_tone"),
        "flirt_level": topic_meta.get("flirt_level"),
        "conversation_mode": conv_mode,
        "context_messages_limit": t_limit,
        "tier_features": {
            "memory_in_prompt": is_premium_tier,
            "deep_personality": (plan_tier or "free").strip().lower() == "premium_plus",
            "pickup_master_eligible": (plan_tier or "free").strip().lower() == "premium_plus",
            "dating_strategy_depth": "full"
            if (plan_tier or "free").strip().lower() == "premium_plus"
            else ("standard" if is_premium_tier else "light"),
        },
        "premium_mode_used": conv_mode == "premium_pickup_master"
        and (plan_tier or "free").strip().lower() in {"premium", "premium_plus"},
        "relationship_stage": stage_info.get("stage"),
        "stage_mutuality_score": stage_info.get("mutuality_score"),
        "stage_energy_score": stage_info.get("energy_score"),
        "suggested_tone": suggested_tone,
        "suggested_conversation_mode": suggested_conv_mode,
        "dating_strategy": {
            "next_action": dating_strategy.get("next_action"),
            "reasoning_tags": dating_strategy.get("reasoning_tags") or [],
        },
        "plan_tier": pt_goal,
        "conversation_goal": conversation_goal_state.to_dict(),
        **(
            {"conversation_goal_metrics": premium_plus_goal_metrics_public(conversation_goal_state, locale=lang)}
            if pt_goal == "premium_plus"
            else {}
        ),
    }

    if not gate["run_generation"] and not (regen in {"light", "flirty", "deep"}):
        return {
            "ok": True,
            "variants": empty_variants,
            "coaching": _merge_coach_hints(coaching, ctx, transcript_lines, effective_mode, plan_tier),
            "ui": ui,
            "recommended_variant": None,
            "recommendation_reason": None,
            "variant_insights": {},
            "meta": {**meta_base, "ai_used": False},
        }

    coach_suffix = (
        _extra_user_coach_block(
            effective_mode=effective_mode,
            ctx=ctx,
            transcript_lines=transcript_lines,
            lang=lang,
        )
        + "\n"
        + (topic_context_for_prompt(topic_meta, lang) if is_premium_tier else _basic_topic_context(topic_meta, lang))
        + _conversation_mode_instruction(conv_mode)
        + capability_prompt_block(pt_goal)
        + (conversation_goal_prompt_extra if is_premium_tier else "")
        + (
            _demo_brain_hook_suffix(db, user_id, transcript_lines)
            + (personalization_prompt_suffix(db, user_id=user_id) if is_premium_tier else "")
            + stage_prompt_hint(
                str(stage_info.get("stage") or "warmup"),
                float(stage_info.get("mutuality_score") or 0.0),
                float(stage_info.get("energy_score") or 0.0),
            )
            + dating_strategy_prompt_block(dating_strategy, locale=lang, plan_tier=(plan_tier or "free").strip().lower())
        )
    )

    async def _run(gen_mode: str) -> dict[str, str]:
        nonlocal gemini_used
        if regen in {"light", "flirty", "deep"}:
            kl = str(peer.get("light") or "")
            kf = str(peer.get("flirty") or "")
            kd = str(peer.get("deep") or "")
            msg = await _gemini_one_line(
                transcript=transcript,
                mode=gen_mode,
                lang=lang,
                me_name=me_name,
                partner_name=partner_name,
                target=regen,
                keep_light=kl,
                keep_flirty=kf,
                keep_deep=kd,
                style_hint=style_hint,
                coach_user_suffix=coach_suffix,
                language_hint=lang_hint,
            )
            merged = {"light": kl, "flirty": kf, "deep": kd}
            if msg and is_text_locale(msg, lang):
                merged[regen] = msg
                gemini_used = True
            return merged
        pack = await _gemini_full_pack(
            transcript=transcript,
            mode=gen_mode,
            lang=lang,
            me_name=me_name,
            partner_name=partner_name,
            style_hint=style_hint,
            coach_user_suffix=coach_suffix,
            language_hint=lang_hint,
        )
        if pack:
            raw = {"light": pack.light or "", "flirty": pack.flirty or "", "deep": pack.deep or ""}
            enforced = _enforce_pack_language(raw, lang)
            if any(enforced.get(k, "").strip() for k in ("light", "flirty", "deep")):
                valid_count = sum(1 for k in ("light", "flirty", "deep") if (enforced.get(k) or "").strip())
                if valid_count >= 1:
                    gemini_used = True
                    return enforced
        return {}

    def _humanize_pack_for_conversion(pack: dict[str, str]) -> dict[str, str]:
        """
        Ensure top-tier "human" feel:
        - if partner asked a direct question, answer it first using my profile (even on fallback)
        - variation across 3 variants (one can end without a question)
        - light flirt ~30% (mostly in flirty)
        """
        try:
            from app.services.ai.direct_questions import detect_direct_intent, render_direct_answer

            partner_last = _partner_last_text(transcript_lines)
            intent = detect_direct_intent(partner_last or "")
            import zlib

            seed_blob = f"{user_id}:{partner_id}:{effective_mode}:{str(ctx.get('text_count') or 0)}".encode("utf-8", errors="ignore")
            seed_base = int(zlib.adler32(seed_blob) & 0xFFFFFFFF)
            if intent and me_profile:
                direct = render_direct_answer(
                    speaker_profile=me_profile,
                    partner_profile=partner_profile,
                    last_user_message=partner_last or "",
                    seed=seed_base,
                )
                if direct:
                    # Put the direct answer into "light" (easy), then keep other modes for play/depth.
                    pack = {**pack, "light": direct}
        except Exception:
            pass

        # Variation: make sure not all end with a question.
        try:
            vals = {k: str(pack.get(k) or "").strip() for k in ("light", "flirty", "deep")}
            if all(v.endswith("?") for v in vals.values() if v):
                # Prefer making "deep" a statement + vibe, to avoid always ending with a question.
                d = vals.get("deep") or ""
                if d:
                    pack["deep"] = d.rstrip("?").rstrip() + "."
        except Exception:
            pass

        return pack

    raw_variants: dict[str, str] = {}
    try:
        raw_variants = asyncio.run(_run(effective_mode))
    except RuntimeError:
        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            raw_variants = loop.run_until_complete(_run(effective_mode))
        finally:
            try:
                loop.close()
            except Exception:
                pass

    if not raw_variants or not any(str(raw_variants.get(k) or "").strip() for k in ("light", "flirty", "deep")):
        raw_variants = _fallback_pack(
            effective_mode,
            partner_name,
            lang,
            last_partner_message=_partner_last_text(transcript_lines),
        )
        gemini_used = False
    else:
        raw_variants = _enforce_pack_language(raw_variants, lang)
        # Encourage semantic diversity across variants.
        try:
            raw_variants = asyncio.run(
                _repair_variation(
                    transcript=transcript,
                    mode=effective_mode,
                    lang=lang,
                    me_name=me_name,
                    partner_name=partner_name,
                    variants=raw_variants,
                    style_hint=style_hint,
                    coach_user_suffix=coach_suffix,
                    language_hint=lang_hint,
                )
            )
        except RuntimeError:
            loop = asyncio.new_event_loop()
            try:
                asyncio.set_event_loop(loop)
                raw_variants = loop.run_until_complete(
                    _repair_variation(
                        transcript=transcript,
                        mode=effective_mode,
                        lang=lang,
                        me_name=me_name,
                        partner_name=partner_name,
                        variants=raw_variants,
                        style_hint=style_hint,
                        coach_user_suffix=coach_suffix,
                        language_hint=lang_hint,
                    )
                )
            finally:
                try:
                    loop.close()
                except Exception:
                    pass

    # Apply "human conversion" layer after generation, before safety filtering.
    raw_variants = _humanize_pack_for_conversion(raw_variants)

    safe = _safe_pack(raw_variants, partner_name or None)
    if len(safe) < 3:
        fb = _fallback_pack(
            effective_mode,
            partner_name,
            lang,
            last_partner_message=_partner_last_text(transcript_lines),
        )
        for k in ("light", "flirty", "deep"):
            if k not in safe or not safe[k]:
                if fb.get(k):
                    rows = filter_chat_suggestions(kind="openers", candidates=[fb[k]], partner_name=partner_name or None)
                    if rows:
                        safe[k] = rows[0].text

    out_variants = {k: safe.get(k, "") for k in ("light", "flirty", "deep")}
    recent_hist = _transcript_text_history(transcript_lines)
    topic_id = str(topic_meta.get("topic") or "general")
    salt_base = f"{partner_id}:{user_id}:{topic_id}:{effective_mode}"

    async def _validate_regen_pack(peer: dict[str, str]) -> dict[str, str]:
        nonlocal gemini_used
        p = {**peer}
        regen_used = False
        for k in ("light", "flirty", "deep"):
            txt = (p.get(k) or "").strip()
            peer_lines = [p.get(x) or "" for x in ("light", "flirty", "deep") if x != k]
            vreason = validate_chat_brain_line(
                txt,
                variant=k,
                recent_lines=recent_hist + peer_lines,
                lang=lang,
                salt=f"{salt_base}:{k}",
            )
            if vreason is None:
                continue
            fb_line = topic_fallback_variant(
                topic_id, k, lang, last_partner_message=_partner_last_text(transcript_lines)
            )
            rows_fb = filter_chat_suggestions(
                kind="openers", candidates=[fb_line], partner_name=partner_name or None, max_len=220
            )
            if rows_fb:
                p[k] = rows_fb[0].text
        if not pack_question_quota_met(p):
            for k in ("light", "flirty", "deep"):
                t = p.get(k) or ""
                if "?" in t or "？" in t:
                    continue
                fb_line = topic_fallback_variant(
                    topic_id, k, lang, last_partner_message=_partner_last_text(transcript_lines)
                )
                if "?" not in fb_line and "？" not in fb_line:
                    continue
                rows_fb = filter_chat_suggestions(
                    kind="openers", candidates=[fb_line], partner_name=partner_name or None, max_len=220
                )
                if rows_fb:
                    p[k] = rows_fb[0].text
                    break
        if regen_used:
            gemini_used = True
        return p

    try:
        out_variants = asyncio.run(_validate_regen_pack(out_variants))
    except RuntimeError:
        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            out_variants = loop.run_until_complete(_validate_regen_pack(out_variants))
        finally:
            try:
                loop.close()
            except Exception:
                pass

    quality_meta: dict[str, dict[str, Any]] = {}
    for k in ("light", "flirty", "deep"):
        q = polish_reply_quality(out_variants.get(k, ""), locale=lang, max_len=220)
        out_variants[k] = str(q.get("text") or "").strip()
        quality_meta[k] = {"quality_score": q["quality_score"], "quality_flags": q["quality_flags"]}
    if lang == "uk":
        from app.services.ai.conversation.contextual_fallback_triples import guard_uk_variant_pack

        out_variants = guard_uk_variant_pack(
            out_variants, last_partner_message=_partner_last_text(transcript_lines)
        )
    try:
        polished_vals = [str(out_variants.get(k) or "").strip() for k in ("light", "flirty", "deep")]
        if polished_vals and all(v.endswith("?") for v in polished_vals if v):
            d = str(out_variants.get("deep") or "").strip()
            if d:
                out_variants["deep"] = d.rstrip("?").rstrip() + "."
    except Exception:
        pass

    tc = int(ctx.get("text_count") or 0)
    insights = _build_variant_insights(out_variants, tc, style_prof)
    best, reco_reason = _pick_recommended(out_variants, insights, effective_mode, tc, style_prof)
    coach_score = assess_conversation(
        last_messages=stage_messages,
        current_user_profile=me_profile,
        partner_profile=partner_profile,
        memory={"style_public": style_public} if is_premium_tier else {},
        conversation_stage=str(stage_info.get("stage") or ""),
        locale=lang,
    ).to_dict()

    try:
        track_event(
            db,
            "ai_stage_detected",
            user_id=int(user_id),
            payload={
                "relationship_stage": stage_info.get("stage"),
                "mutuality_score": stage_info.get("mutuality_score"),
                "energy_score": stage_info.get("energy_score"),
                "next_action": dating_strategy.get("next_action"),
                "reasoning_tags": dating_strategy.get("reasoning_tags") or [],
                "plan_tier": (plan_tier or "free").strip().lower(),
                "partner_user_id": partner_id,
                "ai_provider_used": bool(gemini_used),
            },
        )
    except Exception:
        pass

    return {
        "ok": True,
        "variants": out_variants,
        "coaching": _merge_coach_hints(coaching, ctx, transcript_lines, effective_mode, plan_tier),
        "ui": {**ui, "suggestions_visible": True},
        "recommended_variant": best,
        "recommendation_reason": (reco_reason if best and reco_reason else None),
        "variant_insights": insights,
        "meta": {
            **meta_base,
            "ai_used": bool(gemini_used),
            "quality": quality_meta,
            "coach_score": coach_score if is_premium_tier else None,
        },
    }
