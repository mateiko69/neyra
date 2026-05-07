"""
Conversation closer: public closer_stage taxonomy, safe meeting-leaning copy, copilot prompt hints.

Maps internal detect_stage() stages to: opener | early_chat | engaged | high_interest | stalled | ready_for_meeting
"""

from __future__ import annotations

import re
from typing import Any, Literal

from app.services.ai.ai_fallback_phrases import (
    timed_now_emergency_triple,
    timed_reengage_triple,
    timed_revive_triple,
)
from app.services.ai.ai_request_locale import normalize_ai_request_locale
from app.services.ai.conversation.conversation_stage_engine import detect_stage
from app.services.ai.soft_meeting_ladder_phrases import soft_meeting_ladder_triple

CloserStage = Literal["opener", "early_chat", "engaged", "high_interest", "stalled", "ready_for_meeting"]

_INTERNAL_TO_CLOSER: dict[str, CloserStage] = {
    "opener": "opener",
    "warmup": "early_chat",
    "engaged": "engaged",
    "flirty": "high_interest",
    "connection": "high_interest",
    "meeting_ready": "ready_for_meeting",
}

# `{near}` expands to `_near_clause` (empty string ok).
_MEETING_WALK_NEAR: dict[str, str] = {
    "en": "Maybe coffee or a walk{near} sometime?",
    "uk": "може якось кава чи прогулянка{near}?",
    "ru": "может как-нибудь кофе или прогулка{near}?",
    "es": "¿Un café o un paseo{near} algún día?",
    "pt": "Um café ou um passeio{near} qualquer dia?",
    "fr": "Un café ou une balade{near}, quand ça peut?",
    "de": "Mal Kaffee oder ein Spaziergang{near}?",
    "it": "Un caffè o una passeggiata{near} un giorno?",
    "pl": "Kawa lub spacer{near}, jak będziesz miał(a) ochotę?",
    "tr": "Kahve veya kısa bir yürüyüş{near} nasıl olur?",
    "zh": "要不要{near}一起喝杯咖啡或散个步？",
    "zh-TW": "要不要{near}一起喝杯咖啡或散個步？",
    "ja": "近いうち{near}、コーヒーか散歩どう？",
    "ko": "시간 될 때{near} 커피나 짧게 산책 어때?",
    "hi": "कभी कॉफ़ी या छोटी सैर{near}?",
    "id": "Kopi atau jalan santai{near}?",
    "vi": "Cà phê hoặc đi bộ{near} được không?",
    "th": "ไปคาเฟ่หรือเดินเล่น{near}กันได้ไหม?",
    "ar": "قهوة أو نزهة قصيرة{near}؟",
    "he": "קפה או טיול קצר{near}?",
    "nl": "Koffie of een wandeling{near}?",
    "sv": "Fika eller en promenad{near}?",
    "cs": "Káva nebo procházka{near}?",
    "ro": "O cafea sau o plimbare{near}?",
    "hu": "Kávé vagy egy rövid séta{near}?",
    "el": "Καφές ή ήρεμος περίπατος{near};",
    "da": "Kaffe eller en gang{near}?",
    "fi": "Kahvi tai kävely{near}?",
    "no": "Kaffe eller en tur{near}?",
    "bg": "Кафе или къса разходка{near}?",
}


def soft_meeting_ladder_three(locale: str | None) -> tuple[str, str, str]:
    """Three-step soft meeting framing — full locale coverage."""
    return soft_meeting_ladder_triple(locale)


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


def _q_short(text: str, max_len: int = 320, *, locale: str | None = None) -> str:
    s = (text or "").strip()
    if not s:
        lo = normalize_ai_request_locale(locale or "en")
        if lo != "en":
            a, _, _ = timed_now_emergency_triple(lo)
            s = (a or "").strip()
        if not s:
            s = "What’s been the best part of your day so far?"
    s = re.sub(r"\s+", " ", s)
    if len(s) > max_len:
        s = s[: max_len - 1].rstrip() + "…"
    if "?" not in s:
        s = s.rstrip(".!") + "?"
    return s


def compute_closer_stage(messages: Any, *, stalled_chat: bool) -> tuple[str, dict[str, Any]]:
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
    if loc == "pt":
        return f" em {c}"
    if loc == "it":
        return f" a {c}"
    if loc == "fr":
        return f" à {c}"
    if loc in {"de", "nl"}:
        return f" in {c}"
    if loc == "pl":
        return f" w {c}"
    if loc in {"sv", "da", "no"}:
        return f" i {c}"
    if loc == "fi":
        return f" kohteessa {c}"
    if loc == "cs":
        return f" v {c}"
    if loc == "ro":
        return f" în {c}"
    if loc == "hu":
        return f" ({c})"
    if loc == "tr":
        return f" ({c})"
    if loc in {"zh", "zh-TW", "ja", "ko", "vi", "hi", "id", "th"}:
        return f" ({c})"
    if loc in {"ar", "he", "el", "bg"}:
        return f" — {c}"
    return f" in {c}"


def _meeting_walk_line_with_near(loc: str, near: str) -> str:
    """Second soft-ladder row with optional geographic hint."""
    n = normalize_ai_request_locale(loc or "en")
    tpl = _MEETING_WALK_NEAR.get(n)
    if not tpl:
        for fb in ("de", "fr", "es", "pt", "it", "pl", "ru", "uk", "en"):
            tpl = _MEETING_WALK_NEAR.get(fb)
            if tpl:
                break
    tpl = tpl or _MEETING_WALK_NEAR["en"]
    return _soft_line(tpl.format(near=near or ""))


def closer_meeting_suggestions_three(locale: str, closer_stage: str, *, city: str | None = None) -> list[str]:
    """Three safe localized lines toward continuing or softly meeting."""
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
        a, b, c = timed_revive_triple(loc)
        return [_q_short(a, locale=loc), _q_short(b, locale=loc), _q_short(c, locale=loc)]

    if cs == "ready_for_meeting":
        a, b, c = soft_meeting_ladder_triple(loc)
        if near:
            b = _meeting_walk_line_with_near(loc, near)
        return [_soft_line(a), _soft_line(b), _soft_line(c)]

    if cs == "engaged" and loc != "en":
        a, b, c = timed_reengage_triple(loc)
        return [_q_short(a, locale=loc), _q_short(b, locale=loc), _q_short(c, locale=loc)]

    if cs == "high_interest" and loc != "en":
        a, b, c = timed_revive_triple(loc)
        return [_q_short(a, locale=loc), _q_short(b, locale=loc), _q_short(c, locale=loc)]

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
        x, y, z = timed_now_emergency_triple(loc)
        return [_q_short(x, locale=loc), _q_short(y, locale=loc), _q_short(z, locale=loc)]

    a, b, c = packs_en.get(cs, packs_en["early_chat"])
    return [_q_short(a), _q_short(b), _q_short(c)]


def closer_copilot_prompt_addon(closer_stage: str, locale: str | None) -> str:
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
    """Deterministic EN copilot fallback (locale == en only)."""
    cs = (closer_stage or "").strip().lower()
    low = (last_message or "").lower()

    if cs == "stalled":
        a, b, c = timed_revive_triple("en")
        return [_q_short(a, locale="en"), _q_short(b, locale="en"), _q_short(c, locale="en")]

    if cs == "ready_for_meeting":
        a, b, c = soft_meeting_ladder_triple("en")
        return [_soft_line(a), _soft_line(b), _soft_line(c)]

    if cs == "high_interest":
        return [
            _q_short("Okay I’m curious — what kind of connection actually makes you feel safe?", locale="en"),
            _q_short(
                "If we kept this energy going, would you rather deepen it here first or meet somewhere chill?",
                locale="en",
            ),
            _q_short("What’s your favorite kind of ‘easy’ plan when you’re getting to know someone?", locale="en"),
        ]

    if cs == "engaged":
        return [
            _q_short("What part of that story matters most to you personally?", locale="en"),
            _q_short("When you say that, what are you hoping I understand?", locale="en"),
            _q_short("What would make this conversation feel even more ‘you’?", locale="en"),
        ]

    if cs == "opener":
        a, b, c = timed_now_emergency_triple("en")
        return [_q_short(a, locale="en"), _q_short(b, locale="en"), _q_short(c, locale="en")]

    if continue_mode and ("?" in low or len(low) > 40):
        return [
            _q_short("That’s a nice detail 🙂 what made you think of it?", locale="en"),
            _q_short("I’m curious — what would you want to add if you had one more sentence?", locale="en"),
            _q_short("What’s the next tiny step you’d enjoy talking about here?", locale="en"),
        ]
    a, b, c = timed_now_emergency_triple("en")
    return [_q_short(a, locale="en"), _q_short(b, locale="en"), _q_short(c, locale="en")]


def closer_copilot_fallback_lines(
    locale: str | None,
    closer_stage: str,
    last_message: str,
    continue_mode: bool,
) -> list[str]:
    """
    Three copilot fallback lines for ``closer_stage`` in the viewer's UI locale.

    Non-English locales never use the English template pack; phrase banks only.
    """
    loc = normalize_ai_request_locale(locale or "en")
    if loc == "en":
        return closer_copilot_fallback_base_en(closer_stage, str(last_message or ""), continue_mode)

    cs = (closer_stage or "").strip().lower()
    low = (last_message or "").lower()

    if cs == "stalled":
        a, b, c = timed_revive_triple(loc)
        return [_q_short(a, locale=loc), _q_short(b, locale=loc), _q_short(c, locale=loc)]

    if cs == "ready_for_meeting":
        a, b, c = soft_meeting_ladder_triple(loc)
        return [_soft_line(a), _soft_line(b), _soft_line(c)]

    if cs == "high_interest":
        a, b, c = timed_revive_triple(loc)
        return [_q_short(a, locale=loc), _q_short(b, locale=loc), _q_short(c, locale=loc)]

    if cs == "engaged":
        a, b, c = timed_reengage_triple(loc)
        return [_q_short(a, locale=loc), _q_short(b, locale=loc), _q_short(c, locale=loc)]

    if cs == "opener":
        a, b, c = timed_now_emergency_triple(loc)
        return [_q_short(a, locale=loc), _q_short(b, locale=loc), _q_short(c, locale=loc)]

    # early_chat
    if continue_mode and ("?" in low or len(low) > 40):
        a, b, c = timed_reengage_triple(loc)
        return [_q_short(a, locale=loc), _q_short(b, locale=loc), _q_short(c, locale=loc)]

    a, b, c = timed_now_emergency_triple(loc)
    return [_q_short(a, locale=loc), _q_short(b, locale=loc), _q_short(c, locale=loc)]
