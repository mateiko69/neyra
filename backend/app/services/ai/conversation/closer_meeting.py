"""
Conversation closer: public closer_stage taxonomy, safe meeting-leaning copy, copilot prompt hints.

Maps internal detect_stage() stages to: opener | early_chat | engaged | high_interest | stalled | ready_for_meeting
"""

from __future__ import annotations

import re
from typing import Any, Literal

from app.services.ai.ai_fallback_phrases import timed_now_emergency_triple, timed_revive_triple
from app.services.ai.ai_request_locale import normalize_ai_request_locale
from app.services.ai.conversation.conversation_stage_engine import detect_stage

CloserStage = Literal["opener", "early_chat", "engaged", "high_interest", "stalled", "ready_for_meeting"]

# Narrative map (product language → existing closer_stage values):
# opening → opener | interest → early_chat | comfort → engaged | flirt → high_interest | meeting → ready_for_meeting

_INTERNAL_TO_CLOSER: dict[str, CloserStage] = {
    "opener": "opener",
    "warmup": "early_chat",
    "engaged": "engaged",
    "flirty": "high_interest",
    "connection": "high_interest",
    "meeting_ready": "ready_for_meeting",
}


def soft_meeting_ladder_three(locale: str | None) -> tuple[str, str, str]:
    """
    Three-step soft meeting framing (UA-first product copy). Never imperative \"let's meet\".
    Step 1: observer hint → Step 2: optional coffee/walk → Step 3: reassurance.
    """
    loc = normalize_ai_request_locale(locale or "en")
    if loc == "uk":
        return (
            "це вже звучить як розмова, яку краще продовжити не в чаті 😄",
            "може якось кава чи прогулянка?",
            "без напрягу 🙂",
        )
    if loc == "ru":
        return (
            "это уже звучит как разговор, который логичнее продолжить не в чате 😄",
            "может как-нибудь кофе или прогулка?",
            "без давления 🙂",
        )
    return (
        "This already feels like the kind of conversation that’s easier to continue away from the keyboard 😄",
        "Maybe coffee or a walk sometime?",
        "No pressure 🙂",
    )


def _soft_line(text: str, max_len: int = 320) -> str:
    """Trim only — soft ladder lines may be observational (no forced question mark)."""
    s = (text or "").strip()
    if not s:
        return s
    s = re.sub(r"\s+", " ", s)
    if len(s) > max_len:
        s = s[: max_len - 1].rstrip() + "…"
    return s


def polish_timed_fallback_line(text: str, *, closer_stage: str | None) -> str:
    """Normalize timed-reply fallback rows; soft ladder at ``ready_for_meeting`` keeps observational lines."""
    cs = (closer_stage or "").strip().lower()
    if cs == "ready_for_meeting":
        return _soft_line(text)
    return _q_short(text)


def _q_short(text: str, max_len: int = 320) -> str:
    s = (text or "").strip()
    if not s:
        return "What’s been the best part of your day so far?"
    s = re.sub(r"\s+", " ", s)
    if len(s) > max_len:
        s = s[: max_len - 1].rstrip() + "…"
    if "?" not in s:
        s = s.rstrip(".!") + "?"
    return s


def compute_closer_stage(messages: Any, *, stalled_chat: bool) -> tuple[str, dict[str, Any]]:
    """
    Returns (closer_stage, detect_stage_meta).

    If stalled_chat is True (quiet thread / long pause), closer_stage is forced to stalled.
    """
    if stalled_chat:
        return "stalled", {"stage": "stalled", "mutuality_score": 0.0, "energy_score": 0.0}
    meta = detect_stage(messages)
    internal = str(meta.get("stage") or "warmup")
    cs = _INTERNAL_TO_CLOSER.get(internal, "early_chat")
    return cs, meta


def closer_show_moment_hint(
    *,
    score: int,
    closer_stage: str,
    stage_mr: str,
    total_messages: int,
) -> bool:
    """Soft UI hint when momentum is good but we are not spamming full meeting cards."""
    if total_messages < 8:
        return False
    if score < 65:
        return False
    if stage_mr in {"early", "stalled"}:
        return False
    cs = (closer_stage or "").strip().lower()
    return cs in {"engaged", "high_interest", "ready_for_meeting"}


def _near_clause(locale: str, city: str | None) -> str:
    loc = normalize_ai_request_locale(locale or "en")
    c = (city or "").strip()
    if not c:
        return ""
    if loc == "uk":
        return f" у {c}"
    if loc == "ru":
        return f" в {c}"
    if loc == "es":
        return f" en {c}"
    return f" in {c}"


def closer_meeting_suggestions_three(locale: str, closer_stage: str, *, city: str | None = None) -> list[str]:
    """
    Exactly three safe, low-pressure lines oriented toward continuing or meeting.
    At ``ready_for_meeting``, uses a three-step soft ladder (hint → idea → reassurance); no coercion.
    """
    loc = normalize_ai_request_locale(locale or "en")
    cs = (closer_stage or "").strip().lower()
    if cs not in {
        "opener",
        "early_chat",
        "engaged",
        "high_interest",
        "ready_for_meeting",
        "stalled",
    }:
        cs = "early_chat"
    near = _near_clause(loc, city)

    if cs == "stalled":
        try:
            a, b, c = timed_revive_triple(loc)
        except Exception:
            a, b, c = timed_revive_triple("en")
        return [_q_short(a), _q_short(b), _q_short(c)]

    if cs == "ready_for_meeting":
        a, b, c = soft_meeting_ladder_three(loc)
        if near:
            if loc == "uk":
                b = _soft_line(f"може якось кава чи прогулянка{near}?")
            elif loc == "ru":
                b = _soft_line(f"может как-нибудь кофе или прогулка{near}?")
            else:
                b = _soft_line(f"Maybe coffee or a walk{near} sometime?")
        return [_soft_line(a), _soft_line(b), _soft_line(c)]

    packs_en: dict[str, tuple[str, str, str]] = {
        "opener": (
            "Hey 🙂 what’s one small thing that made today better?",
            "Random curiosity — what are you into lately when you’re not working?",
            "If you could steal one hour for yourself today, what would you spend it on?",
        ),
        "early_chat": (
            "I like how easy this feels 🙂 what would you want me to know about you first?",
            "What’s something small you’re looking forward to this week?",
            "When you message someone new, what usually tells you it’s a good vibe?",
        ),
        "engaged": (
            "What part of this topic actually hits different for you?",
            "When you talk about that, what feeling shows up first?",
            "What would make chatting here feel even easier for you?",
        ),
        "high_interest": (
            "I’m enjoying this way too much to rush it 🙂 what’s one thing you’re picky about in people?",
            "If we kept talking like this, would you rather keep it cozy here or trade stories in person sometime?",
            "No pressure — does a quick coffee ever sound fun, or are you more of a slow-chat person?",
        ),
    }

    if cs in {"opener", "early_chat"} and loc != "en":
        try:
            x, y, z = timed_now_emergency_triple(loc)
            return [_q_short(x), _q_short(y), _q_short(z)]
        except Exception:
            pass

    a, b, c = packs_en.get(cs, packs_en["early_chat"])
    return [_q_short(a), _q_short(b), _q_short(c)]


def closer_copilot_prompt_addon(closer_stage: str, locale: str | None) -> str:
    """Safety-forward instructions appended to chat-copilot system prompt."""
    _ = normalize_ai_request_locale(locale or "en")
    cs = (closer_stage or "").strip().lower()
    guides = {
        "opener": "CONVERSATION_CLOSER: stage=opener (opening) — light, easy replies; one clear curiosity hook; no meeting talk.",
        "early_chat": "CONVERSATION_CLOSER: stage=early_chat (interest) — warm curiosity + personal touch; easy to answer; no meet pressure.",
        "engaged": "CONVERSATION_CLOSER: stage=engaged (comfort) — fewer interrogations; reflect back what they said; deepen connection.",
        "high_interest": "CONVERSATION_CLOSER: stage=high_interest (light flirt) — playful respectful tension; invite replies; never explicit.",
        "stalled": "CONVERSATION_CLOSER: stage=stalled — revive gently (new angle / warmth); do not push a meet-up.",
        "ready_for_meeting": (
            "CONVERSATION_CLOSER: stage=ready_for_meeting — optional soft real-world continuation only: observer hint → gentle coffee/walk idea → "
            "reassurance; NEVER imperative meet commands (no \"let's meet\" / \"давай зустрінемось\"); respect decline."
        ),
    }
    common = (
        "\nSAFETY_CLOSER: Never guilt-trip, spam invites, or sound possessive. "
        "Avoid creepy compliments. Natural pacing only.\n"
    )
    return "\n" + guides.get(cs, guides["early_chat"]) + common


def closer_timed_replies_prompt_addon(closer_stage: str, locale: str | None) -> str:
    """Timed-replies: reuse closer copilot rules + explicit progression toward optional meeting."""
    cs = (closer_stage or "").strip().lower()
    tail = (
        "\nTIMED_REPLIES_PROGRESSION: Advance opener → interest → comfort → light flirt → (only if stage allows) soft meeting hint. "
        "Forward momentum toward an eventual meet without pressure — never command forms.\n"
    )
    if cs == "ready_for_meeting":
        tail += (
            "TIMED_REPLIES_MEETING_SOFT: Each option may use one soft step (hint / gentle idea / reassurance). "
            "No urgent scheduling language.\n"
        )
    return closer_copilot_prompt_addon(closer_stage, locale) + tail


def closer_copilot_fallback_base_en(closer_stage: str, last_message: str, continue_mode: bool) -> list[str]:
    """Three English lines for copilot deterministic fallback; translated by caller."""
    cs = (closer_stage or "").strip().lower()
    low = (last_message or "").lower()

    if cs == "stalled":
        a, b, c = timed_revive_triple("en")
        return [_q_short(a), _q_short(b), _q_short(c)]

    if cs == "ready_for_meeting":
        a, b, c = soft_meeting_ladder_three("en")
        return [_soft_line(a), _soft_line(b), _soft_line(c)]

    if cs == "high_interest":
        return [
            _q_short("Okay I’m curious — what kind of connection actually makes you feel safe?"),
            _q_short("If we kept this energy going, would you rather deepen it here first or meet somewhere chill?"),
            _q_short("What’s your favorite kind of ‘easy’ plan when you’re getting to know someone?"),
        ]

    if cs == "engaged":
        return [
            _q_short("What part of that story matters most to you personally?"),
            _q_short("When you say that, what are you hoping I understand?"),
            _q_short("What would make this conversation feel even more ‘you’?"),
        ]

    if cs == "opener":
        a, b, c = timed_now_emergency_triple("en")
        return [_q_short(a), _q_short(b), _q_short(c)]

    # early_chat default + light hooks from last message
    if continue_mode and ("?" in low or len(low) > 40):
        return [
            _q_short("That’s a nice detail 🙂 what made you think of it?"),
            _q_short("I’m curious — what would you want to add if you had one more sentence?"),
            _q_short("What’s the next tiny step you’d enjoy talking about here?"),
        ]
    a, b, c = timed_now_emergency_triple("en")
    return [_q_short(a), _q_short(b), _q_short(c)]


def closer_copilot_fallback_lines(
    locale: str | None,
    closer_stage: str,
    last_message: str,
    continue_mode: bool,
) -> list[str]:
    """
    Three copilot fallback lines for ``closer_stage``, honoring locale.

    Ukrainian uses native phrase banks only (no English templates).
    Other locales reuse English bases (callers may translate elsewhere).
    """
    loc = normalize_ai_request_locale(locale or "en")
    cs = (closer_stage or "").strip().lower()
    low = (last_message or "").lower()

    if loc != "uk":
        return closer_copilot_fallback_base_en(cs, str(last_message or ""), continue_mode)

    if cs == "stalled":
        a, b, c = timed_revive_triple("uk")
        return [_q_short(a), _q_short(b), _q_short(c)]

    if cs == "ready_for_meeting":
        a, b, c = soft_meeting_ladder_three("uk")
        return [_soft_line(a), _soft_line(b), _soft_line(c)]

    if cs == "high_interest":
        return [
            _q_short("Мені цікаво — який зв’язок для тебе справді відчувається безпечним?"),
            _q_short("Якщо ми й надалі так спілкуватимемось, тобі більше хочеться поглибити це тут чи зустрітися десь спокійно?"),
            _q_short("Який для тебе найзручніший легкий план, коли знайомишся з кимось новим?"),
        ]

    if cs == "engaged":
        return [
            _q_short("Яка частина цієї історії для тебе найважливіша?"),
            _q_short("Коли ти так кажеш, що ти хочеш, щоб я зрозумів(ла)?"),
            _q_short("Що зробило б цю розмову ще більш «твоєю»?"),
        ]

    if cs == "opener":
        a, b, c = timed_now_emergency_triple("uk")
        return [_q_short(a), _q_short(b), _q_short(c)]

    if continue_mode and ("?" in low or len(low) > 40):
        return [
            _q_short("Гарний штрих 🙂 що саме наштовхнуло на цю думку?"),
            _q_short("Цікаво — що б ти хотів(ла) додати, якби мав(ла) ще одне речення?"),
            _q_short("Який наступний маленький крок тут було б приємно обговорити?"),
        ]

    a, b, c = timed_now_emergency_triple("uk")
    return [_q_short(a), _q_short(b), _q_short(c)]
