from __future__ import annotations

from app.domain.matching.compatibility_engine import CompatibilityEngine
from app.domain.matching.config import DEFAULT_WEIGHTS
from app.domain.matching.types import CompatibilityResult
from app.models.profile import Profile


def evaluate_compatibility(me: Profile | None, other: Profile | None) -> CompatibilityResult:
    """Use-case wrapper for compatibility evaluation."""

    return CompatibilityEngine(weights=DEFAULT_WEIGHTS).evaluate(me, other)

