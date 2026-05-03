from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class RecoveryResult:
    state: str  # idle|soft_nudge|revive|let_it_breathe
    message: str
    suggestions: list[str]


_ACK_PAT = re.compile(r"^(ok|k|kk|yeah|yep|yes|no|sure|nice|cool|meh|ок|ага|так|ні|ясно)\b", re.I)
_NEEDY_PAT = re.compile(r"\b(why aren'?t you|why not replying|answer me|please reply|u there|ти де)\b", re.I)
_EMOJI_PAT = re.compile(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]")
_POSITIVE_PAT = re.compile(r"\b(lol|haha|love|cute|nice|sweet|amazing|fun|клас|супер|мил|кайф)\b", re.I)


def _plan(plan_tier: str | None) -> str:
    p = (plan_tier or "free").strip().lower()
    return p if p in {"free", "premium", "premium_plus"} else "free"


def _age_bucket(age_min: int | None) -> str:
    if age_min is None:
        return "unknown"
    if age_min < 15:
        return "<15m"
    if age_min < 60:
        return "15-60m"
    if age_min < 6 * 60:
        return "1-6h"
    if age_min < 24 * 60:
        return "6-24h"
    return ">24h"


def recovery_intervention(
    *,
    messages: list[dict],
    last_message_age_minutes: int | None,
    readiness_score: int | None,
    coach_state: str | None,
    plan_tier: str,
    locale: str | None = None,
) -> RecoveryResult:
    plan = _plan(plan_tier)
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
        return RecoveryResult("idle", "", [])

    age_min = last_message_age_minutes if isinstance(last_message_age_minutes, int) else None
    age_min = max(0, min(60 * 24 * 14, age_min)) if age_min is not None else None
    age = _age_bucket(age_min)

    last = rows[-1]
    last_from_me = last["role"] == "me"

    last8 = rows[-8:]
    me_count = sum(1 for m in rows if m["role"] == "me")
    them_count = sum(1 for m in rows if m["role"] == "them")
    total = me_count + them_count
    balance = 0.0 if total <= 0 else min(me_count, them_count) / max(me_count, them_count)

    short_acks = sum(1 for m in last8 if len(m["text"]) <= 12 and _ACK_PAT.match(m["text"]))
    warmth = sum(1 for m in last8 if _EMOJI_PAT.search(m["text"]) or "!" in m["text"] or _POSITIVE_PAT.search(m["text"]))
    questions = sum(1 for m in last8 if "?" in m["text"])
    rs = readiness_score if isinstance(readiness_score, int) else None
    rs = max(0, min(100, rs)) if rs is not None else None

    # Guardrail: never encourage needy follow-ups.
    if any(_NEEDY_PAT.search(m["text"]) for m in last8 if m["role"] == "me"):
        msg = (
            "Keep it calm—give it some space and come back later."
            if loc == "en"
            else "Лучше спокойно — дай немного пространства и вернись позже."
            if loc == "ru"
            else "Спокійно — дай трохи простору й повернись пізніше."
        )
        return RecoveryResult("let_it_breathe", msg, [])

    # Let it breathe: too soon to follow up if we texted last.
    if last_from_me and age in {"<15m", "15-60m"}:
        msg = (
            "Give it a bit—no need to double-text yet."
            if loc == "en"
            else "Дай немного времени — пока не нужно писать ещё раз."
            if loc == "ru"
            else "Дай трохи часу — поки не треба писати вдруге."
        )
        if plan == "premium_plus":
            msg = (
                "No rush—give it a little space before you follow up."
                if loc == "en"
                else "Без спешки — дай немного пространства перед следующим сообщением."
                if loc == "ru"
                else "Без поспіху — дай трохи простору перед наступним повідомленням."
            )
        return RecoveryResult("let_it_breathe", msg, [])

    # If coach is opportunity, avoid recovery nudges.
    if state == "opportunity":
        return RecoveryResult("idle", "", [])

    # Decide stall severity.
    stalled = age == ">24h" or (age in {"6-24h"} and balance < 0.55) or (age in {"6-24h"} and rs is not None and rs < 40)
    fading = age in {"1-6h", "6-24h"} or (short_acks >= 2 and warmth == 0 and questions == 0)

    # Revive: clearly stalled and safe to attempt.
    if stalled:
        base = (
            "If you want to revive it, keep it light and low-pressure."
            if loc == "en"
            else "Если хочешь оживить — сделай это легко и без давления."
            if loc == "ru"
            else "Якщо хочеш оживити — зроби це легко й без тиску."
        )
        if plan == "premium_plus":
            base = (
                "It looks a bit stalled—if you want, you can revive it with something light and low-pressure."
                if loc == "en"
                else "Похоже, разговор притормозил — если хочешь, оживи его легко и без давления."
                if loc == "ru"
                else "Схоже, розмова трохи пригальмувала — якщо хочеш, оживи її легко й без тиску."
            )
        suggestions = (
            [
                "Hey — random question: what’s your ideal weekend look like?",
                "This made me think of you 😄 what’s been the best part of your week so far?",
                "No rush to reply — but I’m curious, are you more of a coffee or tea person?",
            ]
            if loc == "en"
            else [
                "Случайный вопрос: каким для тебя выглядит идеальный уикенд?",
                "Это напомнило мне о тебе 😄 что было лучшим в твоей неделе?",
                "Без спешки — но любопытно: ты больше за кофе или чай?",
            ]
            if loc == "ru"
            else [
                "Випадкове питання: якими для тебе виглядають ідеальні вихідні?",
                "Це нагадало мені про тебе 😄 що було найкращим у твоєму тижні?",
                "Без поспіху — але цікаво: ти більше за каву чи чай?",
            ]
        )
        suggestions = [s for s in suggestions if not _NEEDY_PAT.search(s)]
        return RecoveryResult("revive", base, suggestions[: (3 if plan == "premium_plus" else 1)])

    # Soft nudge: mild fade and not too soon.
    if fading and (not last_from_me or age not in {"<15m"}):
        msg = (
            "A gentle follow-up can bring the energy back."
            if loc == "en"
            else "Мягкий фоллоу‑ап может вернуть энергию."
            if loc == "ru"
            else "М’який фоллоу‑ап може повернути енергію."
        )
        if plan == "premium_plus":
            msg = (
                "A gentle, specific follow-up can bring the energy back."
                if loc == "en"
                else "Мягкий и конкретный фоллоу‑ап может вернуть энергию."
                if loc == "ru"
                else "М’який і конкретний фоллоу‑ап може повернути енергію."
            )
        suggestions = (
            [
                "Quick one — what are you up to today?",
                "What’s something you’ve been into lately?",
                "What’s your go-to comfort food?",
            ]
            if loc == "en"
            else [
                "Короткий вопрос — чем ты сегодня занимаешься?",
                "Во что ты в последнее время залипаешь/увлекаешься?",
                "Какой у тебя любимый «comfort food»?",
            ]
            if loc == "ru"
            else [
                "Коротке питання — чим ти сьогодні займаєшся?",
                "Чим ти останнім часом реально захопився/лась?",
                "Яка в тебе улюблена «comfort food»?",
            ]
        )
        return RecoveryResult("soft_nudge", msg, suggestions[: (3 if plan == "premium_plus" else 1)])

    return RecoveryResult("idle", "", [])

