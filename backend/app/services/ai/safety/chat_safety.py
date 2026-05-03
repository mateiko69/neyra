from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


_BANNED = ["sex", "nude", "hookup", "come over", "bed", "tonight?"]

_SEXUAL_PAT = re.compile(
    r"\b("
    r"nudes?|hook\s*up|one[-\s]?night|sex(y|iest)?|blowjob|handjob|"
    r"cum|orgasm|anal|threesome|dominant|submissive|choke|spank|"
    r"bedroom|lingerie|sugar\s*daddy|sugar\s*baby|nsfw"
    r")\b",
    re.IGNORECASE,
)
_AGGRESSIVE_PAT = re.compile(r"\b(fuck|bitch|slut|whore|idiot|stupid)\b", re.IGNORECASE)
_MANIPULATIVE_PAT = re.compile(
    r"\b("
    r"you\s*owe\s*me|prove\s*it|if\s*you\s*don't|don't\s*be\s*shy|"
    r"just\s*trust\s*me|i\s*know\s*you\s*want|"
    r"be\s*honest\s*with\s*me\s*now|"
    r"answer\s*me|why\s*are\s*you\s*ignoring"
    r")\b",
    re.IGNORECASE,
)
_GENERIC_PAT = re.compile(
    r"^(hey+|hi+|hello+)(\s*[!.\u2764\u2665\u263a:\)]+)?(\s+how\s+are\s+you\??)?\s*$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class SafetyResult:
    text: str
    flags: list[str]


def sanitize_user_text(text: str) -> str:
    if not text:
        return ""
    return text.strip()


def safe_output_or_none(text: str | None) -> str | None:
    if not text:
        return None
    lowered = text.lower()
    if any(b in lowered for b in _BANNED):
        return None
    return text.strip()


def filter_chat_suggestions(*args: Any, **kwargs: Any):
    """Dual-purpose filter to preserve existing backend usage.

    1) Simple API (as requested):
       filter_chat_suggestions(suggestions: list[str]) -> list[str]

    2) Existing API used by AI endpoints:
       filter_chat_suggestions(kind=..., candidates=..., partner_name=..., max_len=...) -> list[SafetyResult]
    """

    # Simple form: filter_chat_suggestions([\"hi\", ...]) -> [\"hi\", ...]
    if args and isinstance(args[0], list) and not kwargs:
        suggestions: list[str] = args[0]
        safe: list[str] = []
        for s in suggestions:
            if safe_output_or_none(s):
                safe.append(s)
        return safe

    # Existing keyword form for AI endpoints.
    candidates: list[str] = kwargs.get("candidates") or []
    partner_name: str | None = kwargs.get("partner_name")
    max_len: int = int(kwargs.get("max_len") or 180)

    def _normalize(text: str) -> str:
        s = (text or "").strip()
        s = re.sub(r"\s+", " ", s)
        return s

    def _clamp(text: str, limit: int) -> str:
        t = _normalize(text)
        if len(t) <= limit:
            return t
        cut = t[: limit + 1]
        last_space = cut.rfind(" ")
        if last_space >= max(0, limit - 24):
            cut = cut[:last_space]
        return cut.rstrip(" ,.-") + "…"

    results: list[SafetyResult] = []
    seen: set[str] = set()
    for raw in candidates or []:
        flags: list[str] = []
        text = _normalize(raw)
        if not text:
            continue

        if _SEXUAL_PAT.search(text):
            flags.append("sexual_too_early")
        if _AGGRESSIVE_PAT.search(text):
            flags.append("aggressive")
        if _MANIPULATIVE_PAT.search(text):
            flags.append("manipulative")
        if _GENERIC_PAT.match(text):
            flags.append("generic")

        if flags:
            continue

        text = _clamp(text, max_len)
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        results.append(SafetyResult(text=text, flags=[]))

    if results:
        return results[:3]

    name = (partner_name or "").strip()
    prefix = f"{name}, " if name else ""
    fallbacks = [
        f"{prefix}your profile made me smile — what are you into lately?",
        f"{prefix}quick question: what’s something you’re excited about this week?",
        f"{prefix}I’m choosing between two vibes today: coffee walk or cozy movie. You?",
    ]
    return [SafetyResult(text=_clamp(x, max_len), flags=["fallback"]) for x in fallbacks[:3]]

