from __future__ import annotations

import re
from dataclasses import dataclass, asdict
from typing import Any, Literal

from app.services.ai.ai_request_locale import normalize_chat_ai_locale
from app.services.ai.conversation.conversation_stage_engine import detect_stage
from app.services.ai.conversation.dating_strategy_engine import plan_dating_strategy

RecommendedMove = Literal["reply", "ask_question", "flirt", "deepen", "wait", "suggest_meet", "revive"]
MeetingReadinessMeta = Literal["not_ready", "warming_up", "ready_soft", "ready_direct"]

_GENERIC_RE = re.compile(r"\b(hey|hi|hello|how are you|what'?s up|nice|cool|ok|okay)\b[.!?\s]*$", re.I)
_NEEDY_RE = re.compile(r"\b(please reply|answer me|why (aren'?t|are not) you replying|miss you already|don'?t ignore me|ти де)\b", re.I)
_CREEPY_RE = re.compile(r"\b(stalk|obsessed|your body|send pics|alone with me|i know where|creep)\b", re.I)
_SEXUAL_RE = re.compile(r"\b(sexy|horny|nude|nudes|hook up|sleep with|turn me on|bed with)\b", re.I)
_THERAPIST_RE = re.compile(r"\b(hold space|process your feelings|emotional availability|attachment style|trauma response|inner child)\b", re.I)
_POETIC_RE = re.compile(r"\b(soul|destiny|eternity|moonlight|stars aligned|universe brought|my muse)\b", re.I)
_QUESTION_RE = re.compile(r"[?？]")
_POSITIVE_RE = re.compile(r"\b(haha|lol|fun|nice|cute|love|like|great|cool|клас|круто|супер|подоба|цікаво)\b", re.I)


@dataclass(frozen=True)
class CoachScore:
    interest_score: int
    momentum_score: int
    stall_risk: int
    flirt_readiness: int
    meeting_readiness: int
    recommended_move: RecommendedMove
    reason: str
    warning: str | None = None
    meeting_readiness_meta: MeetingReadinessMeta = "not_ready"
    casual_meeting_line: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}


def _clamp(value: float | int) -> int:
    return int(max(0, min(100, round(float(value)))))


def _norm_messages(messages: list[Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for raw in messages or []:
        if isinstance(raw, str):
            text = raw.strip()
            if text:
                out.append({"role": "partner", "text": text})
            continue
        if not isinstance(raw, dict):
            continue
        role = str(raw.get("role") or raw.get("sender") or "").strip().lower()
        if role in {"them", "partner", "other"}:
            role = "partner"
        elif role not in {"me", "partner"}:
            role = "partner"
        text = str(raw.get("text") or raw.get("content") or raw.get("message") or "").strip()
        if text:
            out.append({"role": role, "text": text[:500], "created_at": raw.get("created_at"), "ts_ms": raw.get("ts_ms")})
    return out[-120:]


def _profile_text(profile: Any) -> str:
    if profile is None:
        return ""
    if isinstance(profile, dict):
        vals = [profile.get(k) for k in ("bio", "interests", "relationship_goal", "vibe", "city")]
    else:
        vals = [getattr(profile, k, "") for k in ("bio", "interests", "relationship_goal", "vibe", "city")]
    return " ".join(str(v or "") for v in vals).strip().lower()


def _meeting_meta(score: int, stage: str, *, total: int, me_cnt: int, them_cnt: int) -> MeetingReadinessMeta:
    if score >= 82 and stage == "meeting_ready" and me_cnt >= 5 and them_cnt >= 5 and total >= 16:
        return "ready_direct"
    if score >= 70 and stage in {"engaged", "flirty", "connection", "meeting_ready"} and me_cnt >= 3 and them_cnt >= 3:
        return "ready_soft"
    if score >= 45:
        return "warming_up"
    return "not_ready"


def assess_conversation(
    *,
    last_messages: list[Any],
    current_user_profile: Any = None,
    partner_profile: Any = None,
    memory: dict[str, Any] | None = None,
    conversation_stage: str | None = None,
    locale: str | None = None,
) -> CoachScore:
    messages = _norm_messages(last_messages)
    loc = normalize_chat_ai_locale(locale or "en")
    total = len(messages)
    me_msgs = [m for m in messages if m["role"] == "me"]
    them_msgs = [m for m in messages if m["role"] == "partner"]
    me_cnt = len(me_msgs)
    them_cnt = len(them_msgs)
    texts = [m["text"] for m in messages]
    partner_recent = [m["text"] for m in them_msgs[-5:]]
    last_role = messages[-1]["role"] if messages else None
    trail_me = 0
    for m in reversed(messages):
        if m["role"] == "me":
            trail_me += 1
        else:
            break

    stage_info = detect_stage(messages) if messages else {"stage": "opener", "mutuality_score": 0.0, "energy_score": 0.0}
    stage = (conversation_stage or stage_info.get("stage") or "opener").strip().lower()
    mutuality = float(stage_info.get("mutuality_score") or 0.0)
    energy = float(stage_info.get("energy_score") or 0.0)
    balance = min(me_cnt, them_cnt) / max(1, max(me_cnt, them_cnt))
    avg_partner_len = sum(len(t) for t in partner_recent) / max(1, len(partner_recent))
    partner_short_rate = sum(1 for t in partner_recent if len(t.split()) <= 2) / max(1, len(partner_recent))
    question_rate = sum(1 for t in texts[-12:] if _QUESTION_RE.search(t)) / max(1, min(12, len(texts)))
    positive_rate = sum(1 for t in texts[-12:] if _POSITIVE_RE.search(t) or any(ch in t for ch in ("🙂", "😊", "😄", "😂", "😉"))) / max(1, min(12, len(texts)))
    shared_profile_signal = 0.0
    mine = set(re.findall(r"[a-zа-яіїєґ]{3,}", _profile_text(current_user_profile)))
    theirs = set(re.findall(r"[a-zа-яіїєґ]{3,}", _profile_text(partner_profile)))
    if mine and theirs and len(mine & theirs) > 0:
        shared_profile_signal = 0.08
    mem = memory or {}
    memory_boost = 0.06 if mem and any(mem.get(k) for k in ("user_style", "partner_notes", "dating_preferences", "personalization")) else 0.0

    interest = _clamp(20 + mutuality * 38 + positive_rate * 18 + balance * 14 + min(avg_partner_len, 80) / 80 * 10 + shared_profile_signal * 100)
    momentum = _clamp(15 + energy * 42 + balance * 20 + question_rate * 12 + positive_rate * 11 + (8 if last_role == "partner" else 0))
    stall = _clamp(35 + partner_short_rate * 35 + max(0, trail_me - 1) * 18 - momentum * 0.35 - positive_rate * 12)
    if total < 4:
        stall = max(stall, 45)
    flirt = _clamp(interest * 0.45 + momentum * 0.35 + positive_rate * 20 - partner_short_rate * 18)
    meeting = _clamp(interest * 0.35 + momentum * 0.35 + min(total, 20) * 1.5 + memory_boost * 100 - stall * 0.25)
    if total < 8 or me_cnt < 3 or them_cnt < 3:
        meeting = min(meeting, 42)
    if stage in {"opener", "warmup"}:
        meeting = min(meeting, 62)
    if stage == "meeting_ready":
        meeting = max(meeting, 72)

    strategy = plan_dating_strategy(
        stage_info=stage_info,
        stage_messages=messages,
        last_text_role="me" if last_role == "me" else "partner" if last_role == "partner" else None,
        hours_since_last_text=None,
        run_generation=True,
        trail_me=trail_me,
    )
    action = str(strategy.get("next_action") or "continue")
    recommended: RecommendedMove = "reply"
    warning: str | None = None
    if stall >= 70:
        recommended = "revive" if total >= 4 else "ask_question"
        warning = "Conversation is losing momentum; keep it light and low-pressure."
    elif action == "wait" or (last_role == "me" and trail_me >= 2):
        recommended = "wait"
        warning = "Avoid double-texting too quickly."
    elif meeting >= 72 and stage in {"engaged", "flirty", "connection", "meeting_ready"}:
        recommended = "suggest_meet"
    elif flirt >= 66 and stage in {"engaged", "flirty"}:
        recommended = "flirt"
    elif action == "deepen" or (interest >= 58 and question_rate < 0.25):
        recommended = "deepen"
    elif action == "flirt":
        recommended = "flirt"
    elif interest < 42 or partner_short_rate >= 0.6:
        recommended = "ask_question"

    meta = _meeting_meta(meeting, stage, total=total, me_cnt=me_cnt, them_cnt=them_cnt)
    casual = "З тобою було б цікаво випити каву 🙂" if meta == "ready_soft" and loc == "uk" else None
    reason_map = {
        "wait": "They need space before another nudge.",
        "revive": "The thread is shallow or slowing down, so a soft re-entry is safer.",
        "ask_question": "A simple, specific question gives them an easy way back in.",
        "flirt": "There is enough warmth for a playful step without pushing.",
        "deepen": "Mutual interest is present; add one more personal layer.",
        "suggest_meet": "Momentum is strong enough for a casual, low-pressure meeting hint.",
        "reply": "Keep the rhythm going with a short natural reply.",
    }
    if loc == "uk":
        reason_map.update(
            {
                "wait": "Краще дати трохи простору перед наступним повідомленням.",
                "revive": "Розмова пригальмувала, тому м'який ре-енгейдж без тиску безпечніший.",
                "ask_question": "Просте конкретне питання дасть легкий привід відповісти.",
                "flirt": "Тепла вже достатньо для легкої гри без тиску.",
                "deepen": "Є взаємний інтерес; можна додати трохи глибини.",
                "suggest_meet": "Ритм достатньо сильний для casual натяку на зустріч.",
                "reply": "Підтримай ритм короткою природною відповіддю.",
            }
        )
    return CoachScore(
        interest_score=interest,
        momentum_score=momentum,
        stall_risk=stall,
        flirt_readiness=flirt,
        meeting_readiness=meeting,
        recommended_move=recommended,
        reason=reason_map[recommended],
        warning=warning,
        meeting_readiness_meta=meta,
        casual_meeting_line=casual,
    )


def polish_reply_quality(text: str, *, locale: str | None = None, max_len: int = 220) -> dict[str, Any]:
    loc = normalize_chat_ai_locale(locale or "en")
    original = str(text or "").strip()
    s = re.sub(r"\s+", " ", original).strip()
    flags: list[str] = []
    if not s:
        flags.append("empty")
    if len(s) > max_len:
        flags.append("too_long")
        s = s[:max_len].rsplit(" ", 1)[0].rstrip(" .,;:") or s[:max_len].rstrip()
    low = s.lower()
    if _GENERIC_RE.search(low):
        flags.append("too_generic")
    if _NEEDY_RE.search(low):
        flags.append("too_needy")
    if _POETIC_RE.search(low):
        flags.append("too_poetic")
    if _CREEPY_RE.search(low):
        flags.append("creepy")
    if _SEXUAL_RE.search(low):
        flags.append("overly_sexual")
    if _THERAPIST_RE.search(low):
        flags.append("therapist_like")
    if len(s.split()) > 34:
        flags.append("too_long")

    if flags:
        if loc == "uk":
            s = "Мені цікаво, що тобі в цьому найбільше відгукнулося?"
        elif loc == "ru":
            s = "Мне интересно, что тебе в этом больше всего откликнулось?"
        else:
            s = "I’m curious, what part of that stood out to you most?"
    if s and not _QUESTION_RE.search(s) and len(s.split()) <= 18:
        s = s.rstrip(".! ") + "?"
    score = _clamp(96 - len(set(flags)) * 16 - (8 if original != s else 0))
    return {"text": s[:max_len].strip(), "quality_score": score, "quality_flags": sorted(set(flags))}


def polish_many(candidates: list[str], *, locale: str | None = None, max_len: int = 220) -> tuple[list[str], list[dict[str, Any]]]:
    metas = [polish_reply_quality(c, locale=locale, max_len=max_len) for c in candidates]
    return [m["text"] for m in metas if m["text"]], [{"quality_score": m["quality_score"], "quality_flags": m["quality_flags"]} for m in metas]
