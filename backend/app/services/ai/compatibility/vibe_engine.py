from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class VibeResult:
    score: int
    reasons: list[str]


_WORD_PAT = re.compile(r"[a-zA-Zа-яА-ЯіїєґІЇЄҐ']{3,}")
_STOPWORDS = {
    "the",
    "and",
    "that",
    "this",
    "with",
    "you",
    "your",
    "for",
    "are",
    "but",
    "not",
    "have",
    "just",
    "like",
    "що",
    "це",
    "але",
    "так",
    "ні",
    "для",
    "про",
    "тут",
    "там",
    "ми",
    "ти",
    "вона",
    "він",
    "вони",
}


def _split_csv(s: str) -> list[str]:
    return [x.strip().lower() for x in (s or "").split(",") if x.strip()]


def _tokenize_bio(text: str) -> set[str]:
    words = [w.lower() for w in _WORD_PAT.findall(text or "")]
    return {w for w in words if w not in _STOPWORDS}


def _tone_signature(bio: str, preferred_language: str | None) -> dict[str, int]:
    t = (bio or "").strip()
    sig = {
        "emoji": sum(1 for ch in t if ord(ch) > 0x2600),  # coarse, cheap
        "q": t.count("?"),
        "exc": t.count("!"),
        "len_bucket": 0 if len(t) < 60 else 1 if len(t) < 160 else 2,
        "lang": 1 if (preferred_language or "").strip().lower() in {"uk", "ua", "ukr"} else 0,
    }
    return sig


def compute_vibe_score(
    *,
    viewer_bio: str,
    viewer_interests: str,
    viewer_lifestyle: str,
    viewer_goal: str,
    viewer_language: str | None,
    candidate_bio: str,
    candidate_interests: str,
    candidate_lifestyle: str,
    candidate_goal: str,
    candidate_language: str | None,
    locale: str | None = None,
) -> VibeResult:
    vi = set(_split_csv(viewer_interests))
    ci = set(_split_csv(candidate_interests))
    vl = set(_split_csv(viewer_lifestyle))
    cl = set(_split_csv(candidate_lifestyle))

    bio_v = _tokenize_bio(viewer_bio)
    bio_c = _tokenize_bio(candidate_bio)

    inter_overlap = 0.0
    if vi or ci:
        inter_overlap = (len(vi & ci) / max(1, len(vi | ci))) if (vi | ci) else 0.0
    bio_overlap = 0.0
    if bio_v or bio_c:
        bio_overlap = (len(bio_v & bio_c) / max(1, len(bio_v | bio_c))) if (bio_v | bio_c) else 0.0
    life_overlap = 0.0
    if vl or cl:
        life_overlap = (len(vl & cl) / max(1, len(vl | cl))) if (vl | cl) else 0.0

    goal_v = (viewer_goal or "").strip().lower()
    goal_c = (candidate_goal or "").strip().lower()
    goal_align = 1.0 if goal_v and goal_c and goal_v == goal_c else 0.0

    sig_v = _tone_signature(viewer_bio, viewer_language)
    sig_c = _tone_signature(candidate_bio, candidate_language)
    tone_sim = 1.0
    tone_sim -= 0.12 * min(3, abs(sig_v["q"] - sig_c["q"]))
    tone_sim -= 0.08 * min(3, abs(sig_v["exc"] - sig_c["exc"]))
    tone_sim -= 0.10 * min(2, abs(sig_v["len_bucket"] - sig_c["len_bucket"]))
    tone_sim = max(0.0, min(1.0, tone_sim))

    raw = (
        (inter_overlap * 45.0)
        + (bio_overlap * 18.0)
        + (life_overlap * 15.0)
        + (goal_align * 12.0)
        + (tone_sim * 10.0)
    )
    score = int(round(max(0.0, min(100.0, raw))))

    from app.services.app_language import normalize_app_language

    loc = normalize_app_language(locale or "en")
    loc = loc if loc in {"en", "uk", "ru"} else "en"

    reasons: list[str] = []
    shared = list((vi & ci))[:2]
    if shared:
        if loc == "en":
            reasons.append(f"Shared interests: {', '.join(shared)}")
        elif loc == "ru":
            reasons.append(f"Общие интересы: {', '.join(shared)}")
        else:
            reasons.append(f"Спільні інтереси: {', '.join(shared)}")
    if goal_align:
        if loc == "en":
            reasons.append("Similar relationship goals")  # intentionally broad
        elif loc == "ru":
            reasons.append("Похожие цели отношений")
        else:
            reasons.append("Схожі цілі у стосунках")
    if tone_sim >= 0.82:
        if loc == "en":
            reasons.append("Similar communication energy")
        elif loc == "ru":
            reasons.append("Похожая энергия общения")
        else:
            reasons.append("Схожа енергія спілкування")
    if not reasons:
        if loc == "en":
            reasons.append("Strong profile vibe similarity" if score >= 70 else "Some profile vibe alignment")
        elif loc == "ru":
            reasons.append("Сильное совпадение вайба профилей" if score >= 70 else "Есть небольшое совпадение вайба профилей")
        else:
            reasons.append("Сильна схожість вайбу профілів" if score >= 70 else "Є певна схожість вайбу профілів")

    return VibeResult(score=score, reasons=reasons[:3])

