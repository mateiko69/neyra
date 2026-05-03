from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class EscalationResult:
    voice_ready: bool
    video_ready: bool
    date_ready: bool
    primary_step: str  # none|voice|video|date
    confidence: int  # 0..100
    message: str


_ACK_PAT = re.compile(r"^(ok|k|kk|yeah|yep|yes|no|sure|nice|cool|meh|ок|ага|так|ні|ясно)\b", re.I)
_PUSHY_MEET_PAT = re.compile(r"\b(come over|my place|your place|tonight|зараз|сьогодні ввечері)\b", re.I)
_EMOJI_PAT = re.compile(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]")
_POSITIVE_PAT = re.compile(r"\b(lol|haha|hahaha|love|cute|nice|sweet|amazing|fun|клас|супер|мил|кайф)\b", re.I)


def _normalize_plan_tier(plan_tier: str | None) -> str:
    p = (plan_tier or "free").strip().lower()
    return p if p in {"free", "premium", "premium_plus"} else "free"


def escalation_readiness(
    *,
    messages: list[dict],
    readiness_score: int | None,
    coach_state: str | None,
    plan_tier: str,
    locale: str | None = None,
) -> EscalationResult:
    plan = _normalize_plan_tier(plan_tier)
    from app.services.app_language import normalize_app_language

    loc = normalize_app_language(locale or "en")
    loc = loc if loc in {"en", "uk", "ru"} else "en"
    state = (coach_state or "").strip().lower() or None
    state = state if state in {"idle", "nudge", "opportunity", "caution"} else None

    rows = [
        {"role": str(m.get("role") or "").strip().lower(), "text": str(m.get("text") or "").strip()}
        for m in (messages or [])
    ]
    rows = [m for m in rows if m["role"] in {"me", "them"} and m["text"]]
    rows = rows[-24:]
    if not rows:
        return EscalationResult(False, False, False, "none", 0, "")

    # Basic volume / reciprocity
    me_count = sum(1 for m in rows if m["role"] == "me")
    them_count = sum(1 for m in rows if m["role"] == "them")
    total = me_count + them_count
    balance = 0.0 if total <= 0 else min(me_count, them_count) / max(me_count, them_count)

    # Momentum / dryness (recent window)
    last8 = rows[-8:]
    short_acks = sum(1 for m in last8 if len(m["text"]) <= 12 and _ACK_PAT.match(m["text"]))
    pushy_meet = any(_PUSHY_MEET_PAT.search(m["text"]) for m in last8 if m["role"] == "me")

    # Warmth / engagement
    warm_hits = 0
    for m in last8:
        t = m["text"]
        if _EMOJI_PAT.search(t):
            warm_hits += 1
        if "!" in t:
            warm_hits += 1
        if _POSITIVE_PAT.search(t):
            warm_hits += 1

    # Questions (reciprocity signal)
    q_me = sum(1 for m in last8 if m["role"] == "me" and "?" in m["text"])
    q_them = sum(1 for m in last8 if m["role"] == "them" and "?" in m["text"])

    rs = readiness_score if isinstance(readiness_score, int) else None
    rs_norm = max(0, min(100, rs)) if rs is not None else None

    # Conservative guardrails: never escalate when clearly dry or cautioning
    if state == "caution" or pushy_meet or short_acks >= 3:
        return EscalationResult(False, False, False, "none", 0, "")

    # Build a confidence score from multiple weak signals (deterministic)
    score = 0
    score += min(30, total * 2)  # volume
    score += int(balance * 20)  # reciprocity
    score += min(25, warm_hits * 5)  # warmth
    score += min(15, (q_me + q_them) * 5)  # questions
    if rs_norm is not None:
        score += int((rs_norm - 50) * 0.2)  # -10..+10
    if state == "opportunity":
        score += 8
    if state == "nudge":
        score -= 5
    if short_acks >= 2:
        score -= 10
    score = max(0, min(100, score))

    # Thresholds (Premium Plus gets slightly earlier/richer)
    voice_th = 62 if plan == "premium_plus" else 70
    video_th = 74 if plan == "premium_plus" else 82
    date_th = 82 if plan == "premium_plus" else 90

    # Additional hard requirements to prevent early jumps
    enough_back_and_forth = total >= 8 and me_count >= 3 and them_count >= 3
    strong_back_and_forth = total >= 12 and me_count >= 5 and them_count >= 5 and balance >= 0.65
    mutual_questions = (q_me + q_them) >= 2 and q_them >= 1
    warm_enough = warm_hits >= 2

    voice_ready = enough_back_and_forth and warm_enough and score >= voice_th
    video_ready = strong_back_and_forth and warm_enough and mutual_questions and score >= video_th
    date_ready = strong_back_and_forth and warm_hits >= 3 and mutual_questions and (rs_norm is None or rs_norm >= 70) and score >= date_th

    primary = "none"
    if date_ready:
        primary = "date"
    elif video_ready:
        primary = "video"
    elif voice_ready:
        primary = "voice"

    if primary == "none":
        return EscalationResult(voice_ready, video_ready, date_ready, "none", score, "")

    # One-sentence copy, respectful and light
    if primary == "voice":
        msg = (
            "Good moment for a quick voice note."
            if loc == "en"
            else "Хороший момент для короткого голосового."
            if loc == "ru"
            else "Хороший момент для короткого голосового."
        )
        if plan == "premium_plus":
            msg = (
                "The vibe feels warm—this could be a good moment for a quick voice note."
                if loc == "en"
                else "Вайб тёплый — может быть удачный момент для короткого голосового."
                if loc == "ru"
                else "Вайб теплий — може бути вдалий момент для короткого голосового."
            )
    elif primary == "video":
        msg = (
            "This may be a nice time to suggest a quick call."
            if loc == "en"
            else "Схоже, непоганий момент запропонувати короткий дзвінок."
            if loc == "ru"
            else "Похоже, хороший момент предложить короткий звонок."
        )
        if plan == "premium_plus":
            msg = (
                "Nice momentum here—if it feels right, you could suggest a quick call."
                if loc == "en"
                else "Гарний темп — якщо буде доречно, можна запропонувати короткий дзвінок."
                if loc == "ru"
                else "Хороший темп — если уместно, можно предложить короткий звонок."
            )
    else:
        msg = (
            "You could gently move toward meeting up."
            if loc == "en"
            else "Можна м’яко перейти до зустрічі."
            if loc == "ru"
            else "Можно мягко перейти к встрече."
        )
        if plan == "premium_plus":
            msg = (
                "This feels like a good moment for a gentle next-step invite to meet."
                if loc == "en"
                else "Схоже, гарний момент для м’якого запрошення на наступний крок — зустрітись."
                if loc == "ru"
                else "Похоже, хороший момент для мягкого приглашения на следующий шаг — встретиться."
            )

    return EscalationResult(voice_ready, video_ready, date_ready, primary, score, msg)

