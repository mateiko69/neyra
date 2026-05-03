from __future__ import annotations

import re


def clamp_int(value: float, lo: int = 0, hi: int = 100) -> int:
    return int(max(lo, min(hi, round(value))))


def split_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [v.strip() for v in value.split(",") if v.strip()]


def normalize_tokens(values: list[str]) -> set[str]:
    out: set[str] = set()
    for v in values:
        t = re.sub(r"\s+", " ", v.strip().lower())
        if t:
            out.add(t)
    return out


def jaccard_similarity(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


def safe_lower(s: str | None) -> str:
    return (s or "").strip().lower()

