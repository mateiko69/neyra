"""
Unified deterministic AI fallbacks — single source for safe 200 responses.

Used when Gemini/provider fails or AI is disabled. Deterministic, locale-aware,
three variants per surface (no random churn).
"""

from __future__ import annotations

import hashlib
import logging
import re
from typing import Any

from app.services.ai.ai_fallback_phrases import (
    opener_typed_fallback,
    timed_now_emergency_triple,
    timed_reengage_triple,
    timed_revive_triple,
)
from app.services.ai.conversation.contextual_fallback_triples import uk_emergency_fallback_triple
from app.services.ai.ai_request_locale import normalize_ai_request_locale

logger = logging.getLogger("neyra.ai.fallback")

# Common English tokens that should not appear in Ukrainian fallback copy.
_UK_ENGLISH_LEAK_RE = re.compile(
    r"\b(?:the|and|what|your|you|would|could|that|this|nice|when|where|how|why|about|feel|want|make|more|some|any|can|will|with|from|have|been|just|like|know|tell|think|okay|hey|random|curiosity|something|anything|everything|nothing|really|maybe|please|thanks|sorry)\b",
    re.IGNORECASE,
)


def _fallback_line_has_english_leak_for_uk(text: str) -> bool:
    """Heuristic: Latin-heavy fallback lines that read as English in a Ukrainian UI."""
    t = (text or "").strip()
    if not t:
        return False
    if _UK_ENGLISH_LEAK_RE.search(t):
        return True
    cyrillic = sum(1 for ch in t if "\u0400" <= ch <= "\u04FF")
    latin_long = re.findall(r"[A-Za-z]{4,}", t)
    if cyrillic == 0 and len(latin_long) >= 1:
        return True
    return False


def sanitize_fallback_lines_for_locale(
    lines: list[str],
    locale: str | None,
    *,
    context: str = "",
) -> list[str]:
    """
    For ``locale=uk``, replace lines that look like English leaks with Ukrainian phrase-bank rows.
    Logs ``fallback_locale_used`` when substitution happens.
    """
    loc = normalize_ai_request_locale(locale or "en")
    if loc != "uk" or not lines:
        return list(lines)
    pool = list(uk_emergency_fallback_triple())
    out: list[str] = []
    replaced = False
    for i, line in enumerate(lines):
        s = (line or "").strip()
        if _fallback_line_has_english_leak_for_uk(s):
            rep = pool[i % len(pool)]
            out.append(rep)
            replaced = True
        else:
            out.append(line)
    if replaced:
        logger.info(
            "fallback_locale_used",
            extra={
                "event": "fallback_locale_used",
                "locale": "uk",
                "guard": "english_leak_replace",
                "context": (context or "")[:120],
            },
        )
    return out


def _hash_pick(seed: str, alphabet: list[str], idx: int) -> str:
    """Stable slight variation without RNG nondeterminism across workers."""
    h = hashlib.sha256(f"{seed}:{idx}".encode("utf-8")).hexdigest()
    return alphabet[int(h[:8], 16) % len(alphabet)]


_COPILOT_LABELS: dict[str, tuple[str, str, str]] = {
    "en": ("Light", "Playful", "Deep"),
    "uk": ("Тепло", "Флірт", "Грайливо"),
    "ru": ("Легко", "Флирт", "Глубже"),
    "zh-TW": ("輕鬆", "俏皮", "深入"),
    "zh": ("轻松", "活泼", "深入"),
    "pt": ("Leve", "Brincalhão", "Profundo"),
    "fr": ("Doux", "Taquin", "Profond"),
    "de": ("Locker", "Verspielt", "Tief"),
    "es": ("Ligero", "Juguetón", "Profundo"),
    "it": ("Leggero", "Giocoso", "Profondo"),
    "pl": ("Lekko", "Zalotnie", "Głęboko"),
    "tr": ("Yumuşak", "Oyuncu", "Derin"),
    "ja": ("軽め", "冗談気味", "深め"),
    "ko": ("가볍게", "장난스럽게", "깊게"),
    "ar": ("خفيف", "مرِح", "عميق"),
    "he": ("קליל", "שובב", "עמוק"),
    "hi": ("हल्का", "चंचल", "गहरा"),
}


def copilot_fallback_labels(locale: str | None) -> tuple[str, str, str]:
    n = normalize_ai_request_locale(locale or "en")
    return _COPILOT_LABELS.get(n) or _COPILOT_LABELS["en"]


def copilot_suggestion_rows(
    locale: str | None,
    *,
    last_message: str = "",
    continue_mode: bool = False,
    closer_stage: str | None = None,
) -> list[dict[str, Any]]:
    """
    Three copilot options (light / flirty / deep tone) from phrase banks.
    ``last_message`` + ``continue_mode`` tune variation deterministically.
    When ``closer_stage`` is set, use locale-aware lines (Ukrainian is native; others use EN + translate upstream).
    """
    loc = normalize_ai_request_locale(locale or "en")
    if (closer_stage or "").strip():
        from app.services.ai.conversation.closer_meeting import closer_copilot_fallback_lines

        t0, t1, t2 = closer_copilot_fallback_lines(
            loc,
            str(closer_stage),
            str(last_message or ""),
            bool(continue_mode),
        )
        if loc == "uk":
            logger.info(
                "fallback_locale_used",
                extra={
                    "event": "fallback_locale_used",
                    "locale": "uk",
                    "source": "copilot_suggestion_closer",
                    "closer_stage": str(closer_stage or "")[:48],
                },
            )
        fixed = sanitize_fallback_lines_for_locale([t0, t1, t2], loc, context="copilot_suggestion_closer")
        t0, t1, t2 = fixed[0], fixed[1], fixed[2]
        lb_l, lb_f, lb_d = copilot_fallback_labels(loc)
        return [
            {"label": lb_l, "style": "light", "text": t0},
            {"label": lb_f, "style": "flirty", "text": t1},
            {"label": lb_d, "style": "deep", "text": t2},
        ]
    light, flirty, deep = timed_now_emergency_triple(loc)
    lb_l, lb_f, lb_d = copilot_fallback_labels(loc)
    # Tiny lexical variation hook when continuing/replying (stable hash of tail).
    tail = (last_message or "").strip()
    if continue_mode and tail:
        alt = _hash_pick(tail[-48:], [" 🙂", " 😄", ""], 0)
        if alt and not light.endswith(alt.strip()):
            light = (light.rstrip() + alt)[:320]
    fixed = sanitize_fallback_lines_for_locale([light, flirty, deep], loc, context="copilot_suggestion_default")
    light, flirty, deep = fixed[0], fixed[1], fixed[2]
    return [
        {"label": lb_l, "style": "light", "text": light},
        {"label": lb_f, "style": "flirty", "text": flirty},
        {"label": lb_d, "style": "deep", "text": deep},
    ]


def opener_suggestion_rows(locale: str | None) -> list[dict[str, Any]]:
    """Three typed openers: safe / flirty / smart from phrase bank."""
    rows: list[dict[str, Any]] = []
    for kind, text in opener_typed_fallback(locale or "en")[:3]:
        rows.append({"type": str(kind or "safe"), "style": str(kind or "safe"), "text": str(text or "").strip()})
    return rows


def improve_reply_variants(
    draft: str,
    *,
    locale: str | None,
    user_style: str = "chill",
) -> list[dict[str, str]]:
    """Three local rewrite variants using the same engine as local improver (import inside to avoid cycles)."""
    from app.services.ai.conversation.reply_assistant import improve_draft_locally

    loc = normalize_ai_request_locale(locale or "en")
    rows = improve_draft_locally(
        str(draft or ""),
        [],
        str(user_style or "chill"),
        allow_edgy_mode=False,
        locale=loc,
    )
    out: list[dict[str, str]] = []
    for r in (rows or [])[:3]:
        if isinstance(r, dict) and (r.get("text") or "").strip():
            out.append({"text": str(r.get("text") or "").strip(), "style": str(r.get("style") or "polish")})
    return out


def timed_reply_rows(nudge: str, locale: str | None) -> list[dict[str, Any]]:
    """Maps nudge to timed phrase triple (reengage / revive / now)."""
    loc = normalize_ai_request_locale(locale or "en")
    n = (nudge or "now").strip().lower()
    if n == "reengage":
        a, b, c = timed_reengage_triple(loc)
    elif n == "revive":
        a, b, c = timed_revive_triple(loc)
    else:
        a, b, c = timed_now_emergency_triple(loc)
    return [
        {"style": "light", "text": a},
        {"style": "flirty", "text": b},
        {"style": "deep", "text": c},
    ]


def revive_message_rows(locale: str | None) -> list[dict[str, Any]]:
    """Three revive-style lines for stall UX."""
    loc = normalize_ai_request_locale(locale or "en")
    light, flirty, deep = timed_revive_triple(loc)
    return [
        {"label": "Topic shift", "style": "light", "text": light},
        {"label": "Playful", "style": "flirty", "text": flirty},
        {"label": "Go deeper", "style": "deep", "text": deep},
    ]


def start_strategy_openers(locale: str | None) -> list[dict[str, Any]]:
    """Three opener rows for start-strategy shaped responses (maps typed opener → UI styles)."""
    rows: list[dict[str, Any]] = []
    mapping = {"safe": "light", "flirty": "flirty", "smart": "curious"}
    for kind, text in opener_typed_fallback(locale or "en")[:3]:
        k = str(kind or "safe").lower()
        rows.append({"style": mapping.get(k, "light"), "text": str(text or "").strip()})
    return rows


# --- Meeting / coach helpers (deterministic modules live elsewhere; these are thin adapters.)
#
# - HTTP POST /ai/meeting-readiness uses heuristics only — no Gemini (`ai.py`).
# - POST /ai/recovery → `recovery_rules.recovery_intervention` (deterministic).
# - POST /ai/next-step (minimal body) returns fixed localized triple — no Gemini.
# - POST /ai/next-step via legacy `analysis` uses `suggest_next_step` → EscalationAdvisor fallback.
