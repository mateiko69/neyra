"""
Shared validation for dating AI lines: generic, length, hooks, questions, repetition, locale.
Chat brain: regenerate once on failure, then topic fallback (handled in chat_brain_suggestions).
"""

from __future__ import annotations

import hashlib
import re
from typing import Literal

from app.services.ai.locale import is_text_locale

VariantKey = Literal["light", "flirty", "deep"]

_GENERIC_FORBIDDEN = (
    "tell me more about your hobbies",
    "tell me more about your interests",
    "what are your hobbies",
    "what do you do for fun",
    "interesting tell me more",
    "how was your day",
    "how's your day",
    "nice profile",
    "cool profile",
    "you seem nice",
    "you seem interesting",
    "i'm good how are you",
    "not much you",
    "wyd",
    "hmu",
    "sup",
)

_CREEPY = (
    "send me a photo",
    "send pic",
    "come over tonight",
    "alone at",
    "don't tell anyone",
    "nobody has to know",
)

_MAX_CHARS_CHAT_BRAIN = 240
_MAX_SENTENCES = 2


def sentence_count(text: str) -> int:
    t = (text or "").strip()
    if not t:
        return 0
    parts = re.split(r"(?<=[.!?…])\s+", t)
    return len([p for p in parts if p.strip()])


def _has_explicit_question(text: str) -> bool:
    return "?" in text or "？" in text


def has_reply_hook(text: str) -> bool:
    """Question, binary choice, or wh- invitation."""
    if _has_explicit_question(text):
        return True
    low = (text or "").lower()
    if re.search(r"\b(or|versus|vs\.?|чи|або)\b", low) and len(text) < 160:
        return True
    hooks = (
        "tell me ",
        "curious ",
        "wondering ",
        "what ",
        "how ",
        "which ",
        "when ",
        "where ",
        "who ",
        "шо думаєш",
        "як ти",
        "що думаєш",
        "розкажи",
        "цікаво",
    )
    return any(h in low for h in hooks)


def repeated_phrase_fail(text: str, n: int = 4) -> bool:
    """True if the same n-word chunk appears twice."""
    words = re.findall(r"\w+", (text or "").lower())
    if len(words) < n * 2:
        return False
    seen: set[tuple[str, ...]] = set()
    for i in range(len(words) - n + 1):
        g = tuple(words[i : i + n])
        if g in seen:
            return True
        seen.add(g)
    return False


def _question_required_for_variant(variant: str, salt: str) -> bool:
    """~70% of deep lines must include a question; light/flirty always."""
    v = (variant or "").strip().lower()
    if v in ("light", "flirty"):
        return True
    h = int(hashlib.sha256(salt.encode("utf-8")).hexdigest()[:8], 16)
    return (h % 10) < 7


def _norm_for_dup(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", "", s.lower())).strip()


def validate_chat_brain_line(
    text: str,
    *,
    variant: str,
    recent_lines: list[str],
    lang: str,
    salt: str,
) -> str | None:
    """
    Return rejection reason, or None if OK.
    """
    t = (text or "").strip()
    if not t:
        return "empty"
    if len(t) > _MAX_CHARS_CHAT_BRAIN:
        return "too_long"
    if sentence_count(t) > _MAX_SENTENCES:
        return "too_many_sentences"
    low = t.lower()
    if any(g in low for g in _GENERIC_FORBIDDEN):
        return "generic"
    if any(c in low for c in _CREEPY):
        return "creepy"
    if repeated_phrase_fail(t):
        return "repeated_phrase"
    if not is_text_locale(t, lang):
        return "wrong_language"
    peers_norm = [_norm_for_dup(x) for x in recent_lines[-8:] if x]
    tn = _norm_for_dup(t)
    for pn in peers_norm:
        if tn and pn and (tn == pn or tn in pn or pn in tn):
            return "duplicate"
    if not has_reply_hook(t):
        return "no_hook"
    if _question_required_for_variant(variant, salt) and not _has_explicit_question(t):
        return "no_question"
    return None


def pack_question_quota_met(lines: dict[str, str]) -> bool:
    """At least 2 of 3 variants should carry an explicit question (~70% bar)."""
    texts = [str(lines.get(k) or "").strip() for k in ("light", "flirty", "deep")]
    nq = sum(1 for t in texts if t and _has_explicit_question(t))
    return nq >= 2


def validate_improve_reply_line(
    text: str,
    *,
    lang: str,
    index: int,
    peer_texts: list[str],
    salt: str,
) -> str | None:
    """Validate a single improve-reply suggestion (stricter hook; question ~70% via salt)."""
    t = (text or "").strip()
    if not t:
        return "empty"
    if len(t) > 220:
        return "too_long"
    if sentence_count(t) > _MAX_SENTENCES:
        return "too_many_sentences"
    low = t.lower()
    if any(g in low for g in _GENERIC_FORBIDDEN):
        return "generic"
    if any(c in low for c in _CREEPY):
        return "creepy"
    if repeated_phrase_fail(t):
        return "repeated_phrase"
    if not is_text_locale(t, lang):
        return "wrong_language"
    tn = _norm_for_dup(t)
    for p in peer_texts:
        pn = _norm_for_dup(p)
        if tn and pn and (tn == pn or tn in pn or pn in tn):
            return "duplicate"
    if not has_reply_hook(t):
        return "no_hook"
    idx_salt = f"{salt}:improve:{index}"
    if _question_required_for_variant("deep", idx_salt) and not _has_explicit_question(t):
        return "no_question"
    return None
