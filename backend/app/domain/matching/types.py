from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CompatibilityResult:
    """Deterministic, explainable compatibility result."""

    compatibility_score: int
    score_breakdown: dict[str, int]
    top_reasons: list[str]
    warning_flags: list[str]

