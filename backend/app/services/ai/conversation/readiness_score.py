from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class ReadinessResult:
    score: int
    level: str  # low|medium|high
    insight: str
    tips: list[str]


_ACK_PAT = re.compile(r"^(ok|k|kk|lol|lmao|yeah|yep|yes|no|sure|nice|cool|meh|дякую|ок|ага|так|ні|ясно)\b", re.I)
_QUESTION_PAT = re.compile(r"\?")
_EMOJI_PAT = re.compile(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]")


def _clamp_int(v: int, lo: int = 0, hi: int = 100) -> int:
    return max(lo, min(hi, int(v)))


def _level(score: int) -> str:
    if score < 40:
        return "low"
    if score < 70:
        return "medium"
    return "high"


def score_readiness(
    *,
    messages: list[dict],
    draft: str | None,
    plan_tier: str,
    locale: str | None = None,
) -> ReadinessResult:
    """
    Deterministic v1 readiness score.
    messages: [{role: "me"|"them", text: str}]
    """
    plan = (plan_tier or "free").strip().lower()
    plan = plan if plan in {"free", "premium", "premium_plus"} else "free"

    rows = [
        {"role": str(m.get("role") or "").strip().lower(), "text": str(m.get("text") or "").strip()}
        for m in (messages or [])
    ]
    rows = [m for m in rows if m["role"] in {"me", "them"} and m["text"]]
    rows = rows[-24:]

    me_text = " ".join([m["text"] for m in rows if m["role"] == "me"])
    them_text = " ".join([m["text"] for m in rows if m["role"] == "them"])

    me_chars = len(me_text)
    them_chars = len(them_text)
    total_chars = me_chars + them_chars

    # Start from a neutral baseline.
    score = 55

    # Balance: prefer not wildly one-sided.
    if total_chars >= 60:
        ratio = (min(me_chars, them_chars) / max(me_chars, them_chars)) if max(me_chars, them_chars) > 0 else 0.0
        if ratio < 0.25:
            score -= 18
        elif ratio < 0.45:
            score -= 8
        elif ratio > 0.75:
            score += 4

    # Questions: healthy curiosity.
    me_q = sum(1 for m in rows[-10:] if m["role"] == "me" and _QUESTION_PAT.search(m["text"]))
    if me_q == 0 and len(rows) >= 3:
        score -= 8
    elif me_q >= 2:
        score += 6
    else:
        score += 2

    # Dry chain detection (last 4 from either side).
    last4 = rows[-4:]
    short_ack = sum(1 for m in last4 if len(m["text"]) <= 12 and _ACK_PAT.match(m["text"].strip().lower()))
    if short_ack >= 2:
        score -= 14

    # Tone: small boost for warmth / emotion (emoji or exclamation) without overdoing.
    last_me = next((m["text"] for m in reversed(rows) if m["role"] == "me"), "")
    if _EMOJI_PAT.search(last_me) or "!" in last_me:
        score += 3

    # Draft: if user is typing something substantive, nudge upward.
    d = (draft or "").strip()
    if d:
        if len(d) >= 40:
            score += 4
        elif _QUESTION_PAT.search(d):
            score += 2

    score = _clamp_int(score)
    level = _level(score)

    from app.services.app_language import normalize_app_language

    loc = normalize_app_language(locale or "en")
    loc = loc if loc in {"en", "uk", "ru"} else "en"

    # Insight (always 1 sentence, neutral).
    if loc == "en":
        if level == "high":
            insight = "Nice momentum—keep it light and specific with one clear question."
        elif level == "medium":
            insight = "You’re close—adding one specific question can lift the flow fast."
        else:
            insight = "The flow is a bit flat—try a warm line plus one specific question."
    elif loc == "ru":
        if level == "high":
            insight = "Хороший темп — держи лёгкость и добавь один конкретный вопрос."
        elif level == "medium":
            insight = "Почти — один конкретный вопрос быстро оживит разговор."
        else:
            insight = "Диалог немного сухой — добавь тепло и один конкретный вопрос."
    else:
        if level == "high":
            insight = "Гарний темп — тримай легкість і додай одне конкретне питання."
        elif level == "medium":
            insight = "Майже — одне конкретне питання швидко оживить розмову."
        else:
            insight = "Розмова трохи пласка — додай теплу фразу й одне конкретне питання."

    tips: list[str] = []
    if plan == "premium_plus":
        # At most 2 tips, concrete and non-judgmental.
        if loc == "en":
            if me_q == 0:
                tips.append("Ask about one detail from their profile or last message.")
            if short_ack >= 2:
                tips.append("Replace short replies with a quick feeling + a follow-up question.")
            if not tips:
                tips.append("Try a playful either/or question to make replying easy.")
        elif loc == "ru":
            if me_q == 0:
                tips.append("Спроси про одну деталь из профиля или последнего сообщения.")
            if short_ack >= 2:
                tips.append("Замени короткие ответы на эмоцию + уточняющий вопрос.")
            if not tips:
                tips.append("Попробуй лёгкий вопрос «или/или», чтобы отвечать было проще.")
        else:
            if me_q == 0:
                tips.append("Запитай про одну деталь з профілю або останнього повідомлення.")
            if short_ack >= 2:
                tips.append("Заміни короткі відповіді на емоцію + уточнювальне питання.")
            if not tips:
                tips.append("Спробуй легке «або/або» питання, щоб відповідати було простіше.")
        tips = tips[:2]

    return ReadinessResult(score=score, level=level, insight=insight, tips=tips)

