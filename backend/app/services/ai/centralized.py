from __future__ import annotations

import re
from typing import Iterable

from app.services.ai.ai_request_locale import normalize_ai_request_locale


def _sentences(text: str) -> list[str]:
    s = " ".join((text or "").strip().split())
    if not s:
        return []
    # Split on sentence-like boundaries; keep punctuation.
    parts = re.split(r"(?<=[.!?])\s+", s)
    parts = [p.strip() for p in parts if p and p.strip()]
    return parts


_ROBOTIC_PATTERNS: list[re.Pattern] = [
    re.compile(r"\b(tell me more|could you tell me more|share more|elaborate)\b", re.I),
    re.compile(r"\b(what are your interests|your interests)\b", re.I),
    re.compile(r"\b(please explain|explain more)\b", re.I),
    re.compile(r"\b(i would like to know|i want to know)\b", re.I),
    re.compile(r"\b(what do you think|your thoughts\??|thoughts on that)\b", re.I),
    re.compile(r"(що думаєш|що маєш на увазі)", re.I),
]


def _looks_robotic(text: str) -> bool:
    s = (text or "").strip()
    if not s:
        return False
    if any(p.search(s) for p in _ROBOTIC_PATTERNS):
        return True
    # Heuristic: overly formal + generic.
    if "interests" in s.lower() and s.count("?") <= 1 and len(s) < 80:
        return True
    return False


def _humanize_question(text: str, *, locale: str | None) -> str:
    """
    Make prompts feel human:
    - curiosity + light humor + emotional hook
    - still short and question-ending
    Deterministic (no randomness) to keep tests stable.
    """
    loc = normalize_ai_request_locale(locale or "en")
    s = " ".join((text or "").strip().split())
    if not s:
        return s

    if not _looks_robotic(s):
        return s

    # Replace robotic phrasing with more natural scaffolds.
    if loc == "ru":
        return "Это звучит по-живому 😄 коротко или с контекстом хочешь?"
    if loc == "uk":
        return "Це звучить по-живому 😄 коротко чи з контекстом хочеш розкрити?"
    return "That actually sounds fun 😄 was it more impulse or build-up for you?"


def ensure_short_question(text: str, *, locale: str | None) -> str:
    """1–2 sentences, always ends with '?'."""
    loc = normalize_ai_request_locale(locale or "en")
    s = " ".join((text or "").strip().split())
    if not s:
        if loc == "ru":
            return "Интересно 🙂 ты за короткий апдейт или развернутый?"
        if loc == "uk":
            return "Цікаво 🙂 ти за короткий апдейт чи розгорнуто?"
        return "Nice 🙂 coffee-chat pace or walk-and-talk pace for you?"

    # Humanize away from robotic phrasing first (still deterministic).
    s = _humanize_question(s, locale=loc)

    # Keep at most 2 sentences (prefer preserving an existing question).
    parts = _sentences(s)
    if len(parts) > 2:
        s = " ".join(parts[:2]).strip()
    else:
        s = s.strip()

    # Always end with a question mark.
    s = s.rstrip()
    if not s.endswith("?"):
        s = s.rstrip(".!… ")
        s = f"{s}?"

    # Keep short.
    return s[:220]


def normalize_triplet(options: Iterable[str], *, locale: str | None, fallback: list[str] | None = None) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in list(options or []):
        s = ensure_short_question(str(raw or ""), locale=locale).strip()
        if not s:
            continue
        # Add a tiny emotional hook if it's too dry (deterministic rules).
        loc = normalize_ai_request_locale(locale or "en")
        if "?" in s and len(s) < 70 and ("😄" not in s and "🙂" not in s and "😉" not in s):
            if loc in {"en", "uk", "ru"} and ("!" not in s) and s.lower().startswith(("nice", "cool", "ok", "interesting", "класс", "круто", "цікаво", "клас")):
                s = s.replace("?", " 🙂?", 1)
        k = s.lower()
        if k in seen:
            continue
        seen.add(k)
        out.append(s)
        if len(out) >= 3:
            break

    fb = fallback or [
        ensure_short_question("", locale=locale),
        ensure_short_question("", locale=locale),
        ensure_short_question("", locale=locale),
    ]
    for raw in fb:
        if len(out) >= 3:
            break
        s = ensure_short_question(str(raw or ""), locale=locale).strip()
        if not s:
            continue
        k = s.lower()
        if k in seen:
            continue
        seen.add(k)
        out.append(s)

    return out[:3]


def fallback_reply_triplet(*, locale: str | None) -> list[str]:
    """Localized reply suggestions — full MVP coverage via timed-reply phrase bank."""
    from app.services.ai.ai_fallback_phrases import timed_now_emergency_triple

    a, b, c = timed_now_emergency_triple(locale)
    return [a, b, c]


def fallback_opener_triplet(*, locale: str | None) -> list[str]:
    from app.services.ai.ai_fallback_phrases import opener_typed_fallback

    rows = opener_typed_fallback(locale)
    return [t for _, t in rows[:3]]

