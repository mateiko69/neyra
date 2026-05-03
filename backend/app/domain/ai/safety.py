from __future__ import annotations

import re


class SafetyPolicy:
    """Simple deterministic safety layer for generated messages.

    Goals:
    - No harassment
    - No manipulation
    - No explicit sexual content by default
    - Keep it lightweight and testable (no heavy NLP)
    """

    _GENERIC_BANS = (
        "hi, how are you",
        "how are you",
        "привіт, як справи",
        "як справи",
    )

    # Not exhaustive; this is a baseline guardrail.
    _EXPLICIT_PATTERNS = (
        r"\bsex\b",
        r"\bnudes?\b",
        r"\bfuck\b",
        r"\bporn\b",
        r"\bсекс\b",
        r"\bнюд(и|си)?\b",
    )

    _HARASSMENT_PATTERNS = (
        r"\b(slut|whore)\b",
        r"\bсука\b",
    )

    # Keep manipulation narrow: coercive/pressure commands, not cheesy compliments.
    _MANIPULATION_PATTERNS = (
        r"\b(you must|you have to)\s+(send|pay|give|do)\b",
        r"\bти повин(ен|на)\s+(скинути|заплатити|дати|зробити)\b",
    )

    @classmethod
    def validate(cls, text: str, *, allow_edgy_mode: bool = False) -> list[str]:
        """Returns list of safety flags (empty means OK)."""

        flags: list[str] = []
        t = (text or "").strip().lower()
        if not t:
            return ["empty_message"]

        if any(b in t for b in cls._GENERIC_BANS):
            flags.append("generic_message")

        for pat in cls._HARASSMENT_PATTERNS:
            if re.search(pat, t, flags=re.IGNORECASE):
                flags.append("harassment")
                break

        for pat in cls._MANIPULATION_PATTERNS:
            if re.search(pat, t, flags=re.IGNORECASE):
                flags.append("manipulation")
                break

        if not allow_edgy_mode:
            for pat in cls._EXPLICIT_PATTERNS:
                if re.search(pat, t, flags=re.IGNORECASE):
                    flags.append("explicit_content")
                    break

        return sorted(set(flags))

    @classmethod
    def filter_or_fallback(cls, text: str, *, allow_edgy_mode: bool = False, fallback: str) -> tuple[str, list[str]]:
        flags = cls.validate(text, allow_edgy_mode=allow_edgy_mode)
        if flags:
            safe_flags = [f for f in flags if f != "generic_message"]
            # Generic-only can be fixed by falling back.
            return fallback, flags if safe_flags else flags
        return text, []

