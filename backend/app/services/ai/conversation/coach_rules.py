from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class CoachAction:
    type: str
    label: str


@dataclass(frozen=True)
class CoachResult:
    state: str  # idle|nudge|opportunity|caution
    message: str
    actions: list[CoachAction]


_ACK_PAT = re.compile(r"^(ok|k|kk|yeah|yep|yes|no|sure|nice|cool|meh|ок|ага|так|ні|ясно)\b", re.I)
_GENERIC_OPENER_PAT = re.compile(r"\b(how are you|як справи)\b", re.I)
_MEETUP_PUSHY_PAT = re.compile(r"\b(come over|my place|your place|tonight|зараз|сьогодні ввечері)\b", re.I)
_EMOJI_PAT = re.compile(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]")


def coach_intervention(
    *,
    messages: list[dict],
    draft: str | None,
    readiness_score: int | None,
    plan_tier: str,
    locale: str | None = None,
) -> CoachResult:
    plan = (plan_tier or "free").strip().lower()
    plan = plan if plan in {"free", "premium", "premium_plus"} else "free"

    rows = [
        {"role": str(m.get("role") or "").strip().lower(), "text": str(m.get("text") or "").strip()}
        for m in (messages or [])
    ]
    rows = [m for m in rows if m["role"] in {"me", "them"} and m["text"]]
    rows = rows[-24:]

    d = (draft or "").strip()
    last_me = next((m["text"] for m in reversed(rows) if m["role"] == "me"), "")
    last_them = next((m["text"] for m in reversed(rows) if m["role"] == "them"), "")

    # Signals
    recent_me_q = sum(1 for m in rows[-10:] if m["role"] == "me" and "?" in m["text"])
    last4 = rows[-4:]
    short_ack = sum(1 for m in last4 if len(m["text"]) <= 12 and _ACK_PAT.match(m["text"].strip().lower()))
    warm = bool(_EMOJI_PAT.search(last_them or "") or "!" in (last_them or ""))

    rs = readiness_score if isinstance(readiness_score, int) else None
    from app.services.app_language import normalize_app_language

    loc = normalize_app_language(locale or "en")
    loc = loc if loc in {"en", "uk", "ru"} else "en"

    def _label(key: str) -> str:
        if loc == "en":
            return {
                "rewrite_polish": "Rewrite (Polish)",
                "add_question": "Add a question",
                "ask_better": "Ask a better question",
                "voice_note": "Try a voice note",
                "next_step": "Suggest next step",
            }[key]
        if loc == "ru":
            return {
                "rewrite_polish": "Переписать (улучшить)",
                "add_question": "Добавить вопрос",
                "ask_better": "Задать лучший вопрос",
                "voice_note": "Попробовать голосовое",
                "next_step": "Предложить следующий шаг",
            }[key]
        return {
            "rewrite_polish": "Переписати (покращити)",
            "add_question": "Додати питання",
            "ask_better": "Поставити краще питання",
            "voice_note": "Спробувати голосове",
            "next_step": "Запропонувати наступний крок",
        }[key]

    def _msg(key: str) -> str:
        if loc == "en":
            return {
                "dry_soften": "This may feel a bit dry—soften it and add one specific question.",
                "abrupt_softer": "This might feel too abrupt—try a softer step first.",
                "abrupt_respectful": "This might feel abrupt—try a respectful, lighter invite first.",
                "ask_specific": "Try asking something specific instead of a short reply.",
                "lift_fast": "A specific question will lift the flow fast.",
                "good_momentum": "Good momentum—this could be a nice moment to deepen the vibe.",
                "great_vibe": "Great vibe—consider a voice note or a gentle next-step invite.",
            }[key]
        if loc == "ru":
            return {
                "dry_soften": "Может звучать суховато — смягчи и добавь один конкретный вопрос.",
                "abrupt_softer": "Может быть слишком резко — лучше сделать шаг мягче.",
                "abrupt_respectful": "Может прозвучать резко — попробуй более лёгкое, уважительное приглашение.",
                "ask_specific": "Попробуй задать конкретный вопрос вместо короткого ответа.",
                "lift_fast": "Один конкретный вопрос быстро оживит разговор.",
                "good_momentum": "Хороший темп — сейчас можно чуть углубить вайб.",
                "great_vibe": "Отличный вайб — можно попробовать голосовое или мягко предложить следующий шаг.",
            }[key]
        return {
            "dry_soften": "Може звучати сухо — пом’якши й додай одне конкретне питання.",
            "abrupt_softer": "Може бути занадто різко — спробуй спочатку м’якший крок.",
            "abrupt_respectful": "Може звучати різко — спробуй легше, поважне запрошення.",
            "ask_specific": "Спробуй поставити конкретне питання замість короткої відповіді.",
            "lift_fast": "Одне конкретне питання швидко оживить розмову.",
            "good_momentum": "Гарний темп — це може бути вдалий момент поглибити вайб.",
            "great_vibe": "Класний вайб — можна спробувати голосове або м’яко запропонувати наступний крок.",
        }[key]

    # CAUTION: draft is risky / too dry / too generic
    if d:
        if _GENERIC_OPENER_PAT.search(d) or (len(d) <= 8 and _ACK_PAT.match(d.lower())):
            actions = []
            if plan != "free":
                actions.append(CoachAction(type="rewrite", label=_label("rewrite_polish")))
                actions.append(CoachAction(type="ask_question", label=_label("add_question")))
            return CoachResult(
                state="caution",
                message=_msg("dry_soften"),
                actions=actions[:2],
            )
        if _MEETUP_PUSHY_PAT.search(d) and plan == "free":
            return CoachResult(
                state="caution",
                message=_msg("abrupt_softer"),
                actions=[],
            )
        if _MEETUP_PUSHY_PAT.search(d) and plan != "free":
            return CoachResult(
                state="caution",
                message=_msg("abrupt_respectful"),
                actions=[CoachAction(type="date_step", label=_label("next_step"))][:2],
            )

    # NUDGE: weak/dry flow
    low_flow = (rs is not None and rs < 40) or short_ack >= 2 or (recent_me_q == 0 and len(rows) >= 4)
    if low_flow:
        actions = []
        if plan == "free":
            # Occasional nudge only: no actions
            return CoachResult(state="nudge", message=_msg("ask_specific"), actions=[])
        actions.append(CoachAction(type="rewrite", label=_label("rewrite_polish")))
        actions.append(CoachAction(type="ask_question", label=_label("ask_better")))
        return CoachResult(state="nudge", message=_msg("lift_fast"), actions=actions[:2])

    # OPPORTUNITY: warm + engaged
    high_flow = (rs is not None and rs >= 70) or warm
    if high_flow and plan != "free":
        actions = [CoachAction(type="voice_step", label=_label("voice_note")), CoachAction(type="date_step", label=_label("next_step"))]
        msg = _msg("good_momentum")
        if plan == "premium_plus":
            msg = _msg("great_vibe")
        return CoachResult(state="opportunity", message=msg, actions=actions[:2])

    return CoachResult(state="idle", message="", actions=[])

