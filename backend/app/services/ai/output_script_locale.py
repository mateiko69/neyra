from __future__ import annotations

import re

from app.services.ai.ai_request_locale import normalize_ai_request_locale

_CYRILLIC_RE = re.compile(r"[\u0400-\u04FF\u0500-\u052F\u2DE0-\u2DFF\uA640-\uA69F]")
_UK_MARKERS_RE = re.compile(r"[іїєґІЇЄҐ]")
_RU_MARKERS_RE = re.compile(r"[ыэёъЫЭЁЪ]")


def _primary_tag(locale: str) -> str:
    loc = normalize_ai_request_locale(locale)
    if not loc:
        return "en"
    return loc.split("-", 1)[0].lower()


def _letter_counts(text: str) -> dict[str, int]:
    counts = {
        "latin": 0,
        "cyrillic": 0,
        "arabic": 0,
        "hebrew": 0,
        "devanagari": 0,
        "han": 0,
        "kana": 0,
        "hangul": 0,
        "thai": 0,
        "greek": 0,
        "other": 0,
    }
    for ch in text or "":
        code = ord(ch)
        if (0x0041 <= code <= 0x007A) or (0x00C0 <= code <= 0x024F):
            counts["latin"] += 1
        elif 0x0400 <= code <= 0x052F:
            counts["cyrillic"] += 1
        elif 0x0600 <= code <= 0x06FF:
            counts["arabic"] += 1
        elif 0x0590 <= code <= 0x05FF:
            counts["hebrew"] += 1
        elif 0x0900 <= code <= 0x097F:
            counts["devanagari"] += 1
        elif 0x4E00 <= code <= 0x9FFF:
            counts["han"] += 1
        elif (0x3040 <= code <= 0x30FF) or (0x31F0 <= code <= 0x31FF):
            counts["kana"] += 1
        elif 0xAC00 <= code <= 0xD7AF:
            counts["hangul"] += 1
        elif 0x0E00 <= code <= 0x0E7F:
            counts["thai"] += 1
        elif 0x0370 <= code <= 0x03FF:
            counts["greek"] += 1
        elif ch.isdigit() or ch.isspace() or ch in ".,!?'\"“”‘’—–:;()[]{{}}":
            pass
        else:
            counts["other"] += 1
    return counts


def _script_group_for_locale(locale: str) -> str:
    canon = normalize_ai_request_locale(locale)
    low = canon.lower()
    primary = low.split("-", 1)[0] if low else "en"
    if primary in {"uk", "ru", "bg"}:
        return "cyrillic"
    if primary == "sr":
        return "cyrillic"
    if primary == "ar":
        return "arabic"
    if primary in {"he", "iw"}:
        return "hebrew"
    if primary == "hi":
        return "devanagari"
    if primary == "th":
        return "thai"
    if primary == "ja" or low == "jp":
        return "kana"
    if primary == "ko":
        return "hangul"
    if primary == "zh" or canon.startswith("zh"):
        return "han"
    if primary == "el":
        return "greek"
    return "latin"


def _detect_mixed_scripts(text: str) -> bool:
    c = _letter_counts(text)
    alpha_total = sum(c[k] for k in c if k != "other")
    if alpha_total < 6:
        return False
    active = [k for k, v in c.items() if k != "other" and v >= 3]
    return len(active) >= 2


def _uk_ru_consistent(text: str, locale: str) -> bool:
    t = text or ""
    uk_m = len(_UK_MARKERS_RE.findall(t))
    ru_m = len(_RU_MARKERS_RE.findall(t))
    p = _primary_tag(locale)
    if p == "uk" and ru_m >= 2 and uk_m == 0:
        return False
    if p == "ru" and uk_m >= 2 and ru_m == 0:
        return False
    return True


def sniff_dominant_script_for_log(text: str) -> str:
    """Rough script bucket for structured logging (not a BCP-47 language ID)."""
    t = (text or "").strip()
    if not t:
        return ""
    c = _letter_counts(t)
    alpha = {k: v for k, v in c.items() if k != "other" and v > 0}
    if not alpha:
        return "none"
    return max(alpha, key=alpha.get)


def text_matches_requested_locale(text: str, locale: str | None) -> bool:
    """Heuristic: dominant script should match the locale’s typical writing system."""
    loc = normalize_ai_request_locale(locale)
    t = (text or "").strip()
    if not t:
        return False

    if loc == "en":
        cyr = len(_CYRILLIC_RE.findall(t))
        lat = len(re.findall(r"[A-Za-z]", t))
        total_alpha = cyr + lat
        if total_alpha < 8:
            return cyr == 0
        return cyr <= max(1, int(total_alpha * 0.15))

    expected = _script_group_for_locale(loc)
    c = _letter_counts(t)
    alpha_total = sum(c[k] for k in c if k != "other")
    if alpha_total < 6:
        return True

    if _detect_mixed_scripts(t):
        return False

    dominant = max((k for k in c if k != "other"), key=lambda k: c[k], default="latin")
    if c[dominant] <= 0:
        return True

    if expected == "latin":
        ok = dominant == "latin"
    elif expected == "kana":
        ok = dominant in {"kana", "han"} and c["latin"] <= int(alpha_total * 0.35)
    elif expected == "han":
        ok = dominant == "han" or (dominant == "kana" and c["han"] >= int(alpha_total * 0.2))
    else:
        ok = dominant == expected

    if not ok:
        return False
    if expected == "cyrillic":
        return _uk_ru_consistent(t, loc)
    return True
