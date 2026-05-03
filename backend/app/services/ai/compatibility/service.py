from __future__ import annotations

import time
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models.profile import Profile
from app.services.ai.compatibility.vibe_engine import compute_vibe_score
from app.services.ai.compatibility.visual_stub import VisualScorer
from app.services.analytics import track_event
from app.services.trust.profile_quality import compute_profile_quality
from app.services.trust.verification_state import is_verified_profile


@dataclass(frozen=True)
class CompatibilityResult:
    score: int
    level: str  # low|medium|high
    reasons: list[str]
    vibe_score: int | None
    visual_score: int | None
    symmetry_score: int | None
    available: bool


def _bucket(score: int) -> str:
    if score >= 80:
        return "high"
    if score >= 55:
        return "medium"
    return "low"


def _plan(plan_tier: str | None) -> str:
    p = (plan_tier or "free").strip().lower()
    return p if p in {"free", "premium", "premium_plus"} else "free"


def _is_profile_verified_approved(profile: Profile | None) -> bool:
    return is_verified_profile(profile)


def _is_low_quality(profile: Profile | None) -> bool:
    if not profile:
        return False
    try:
        q = compute_profile_quality(profile)
        return bool(q and q.quality_flag == "low_quality")
    except Exception:
        return False


class _TtlCache:
    def __init__(self, ttl_s: float, max_items: int = 2048):
        self.ttl_s = ttl_s
        self.max_items = max_items
        self._data: dict[str, tuple[float, CompatibilityResult]] = {}

    def get(self, key: str) -> CompatibilityResult | None:
        item = self._data.get(key)
        if not item:
            return None
        ts, value = item
        if (time.time() - ts) > self.ttl_s:
            self._data.pop(key, None)
            return None
        return value

    def set(self, key: str, value: CompatibilityResult) -> None:
        if len(self._data) >= self.max_items:
            # Cheap eviction: drop ~10% oldest by insertion time.
            keys = sorted(self._data.items(), key=lambda kv: kv[1][0])
            for k, _ in keys[: max(1, int(self.max_items * 0.1))]:
                self._data.pop(k, None)
        self._data[key] = (time.time(), value)


_CACHE = _TtlCache(ttl_s=60.0, max_items=4096)


class CompatibilityService:
    def __init__(self):
        self._visual = VisualScorer()

    def score_pair(
        self,
        *,
        viewer: Profile,
        candidate: Profile,
        plan_tier: str,
        locale: str | None = None,
        db: Session | None = None,
        emit_trust_impact: bool = True,
    ) -> CompatibilityResult:
        plan = _plan(plan_tier)
        cache_key = f"compat:v1:{viewer.id}:{candidate.id}:{plan}"
        cached = _CACHE.get(cache_key)
        if cached:
            return cached

        vibe = compute_vibe_score(
            viewer_bio=getattr(viewer, "bio", "") or "",
            viewer_interests=getattr(viewer, "interests", "") or "",
            viewer_lifestyle=getattr(viewer, "lifestyle_tags", "") or "",
            viewer_goal=getattr(viewer, "relationship_goal", "") or "",
            viewer_language=getattr(viewer, "preferred_language", None),
            candidate_bio=getattr(candidate, "bio", "") or "",
            candidate_interests=getattr(candidate, "interests", "") or "",
            candidate_lifestyle=getattr(candidate, "lifestyle_tags", "") or "",
            candidate_goal=getattr(candidate, "relationship_goal", "") or "",
            candidate_language=getattr(candidate, "preferred_language", None),
            locale=locale,
        )

        vibe_score = vibe.score
        visual_score: int | None = None
        symmetry_score: int | None = None
        unusable_reason_bucket: str | None = None

        if plan == "premium_plus":
            visual = self._visual.score_pair(viewer=viewer, candidate=candidate)
            visual_score = visual.visual_score
            symmetry_score = visual.symmetry_score
            unusable_reason_bucket = visual.unusable_reason_bucket

        # v1 blend: vibe is primary, visual is a soft modifier (Premium Plus only).
        score = int(round(vibe_score))
        if plan == "premium_plus" and visual_score is not None:
            score = int(round((0.85 * float(vibe_score)) + (0.15 * float(visual_score))))

        # Trust multiplier (subtle, v1). Applied after vibe/visual blend.
        cand_verified = _is_profile_verified_approved(candidate)
        cand_low_quality = _is_low_quality(candidate)
        trust_factor = 1.0
        if cand_verified:
            trust_factor *= 1.08
        if cand_low_quality:
            trust_factor *= 0.93
        if trust_factor != 1.0:
            score = int(round(float(score) * float(trust_factor)))
            score = max(0, min(100, score))
        level = _bucket(score)
        available = vibe_score is not None  # per decision: vibe-only is still available

        reasons = vibe.reasons[:]
        # Only mention visual when it exists.
        from app.services.app_language import normalize_app_language

        loc = normalize_app_language(locale or "en")
        loc = loc if loc in {"en", "uk", "ru"} else "en"

        if plan == "premium_plus" and visual_score is not None:
            reasons = (
                ["Strong visual harmony estimate"]
                if loc == "en"
                else ["Сильная оценка визуальной гармонии"]
                if loc == "ru"
                else ["Сильна оцінка візуальної гармонії"]
            ) + reasons
        # Soft trust reasons (tier-shaped later).
        if cand_verified:
            reasons = (
                ["Verified profile"]
                if loc == "en"
                else ["Профиль подтверждён"]
                if loc == "ru"
                else ["Профіль підтверджено"]
            ) + reasons
        if cand_low_quality:
            reasons = (
                ["Lower profile quality signal"]
                if loc == "en"
                else ["Низкий сигнал качества профиля"]
                if loc == "ru"
                else ["Низький сигнал якості профілю"]
            ) + reasons

        # Backend analytics (no embeddings/photos in payload).
        if plan == "premium_plus":
            if visual_score is not None:
                if db is not None:
                    track_event(
                        db,
                        "ai_visual_compatibility_used",
                        user_id=getattr(viewer, "user_id", None),
                        payload={
                            "plan_tier": plan,
                            "has_visual_score": True,
                            "has_symmetry_score": symmetry_score is not None,
                            "unusable_reason_bucket": None,
                        },
                    )
            else:
                if db is not None:
                    track_event(
                        db,
                        "ai_visual_compatibility_unavailable",
                        user_id=getattr(viewer, "user_id", None),
                        payload={
                            "plan_tier": plan,
                            "has_visual_score": False,
                            "has_symmetry_score": False,
                            "unusable_reason_bucket": unusable_reason_bucket or "unknown",
                        },
                    )

        # Aggregate trust impact analytics (avoid noisy batch emits).
        if emit_trust_impact and db is not None and (cand_verified or cand_low_quality):
            track_event(
                db,
                "trust_impact_on_match",
                user_id=getattr(viewer, "user_id", None),
                payload={
                    "surface": "compatibility_score",
                    "plan_tier": plan,
                    "candidate_verified": bool(cand_verified),
                    "candidate_low_quality": bool(cand_low_quality),
                    "trust_factor": trust_factor,
                },
            )

        # Tier shaping
        reasons = reasons[: (3 if plan == "premium_plus" else 1 if plan == "premium" else 0)]

        result = CompatibilityResult(
            score=score,
            level=level,
            reasons=reasons,
            vibe_score=vibe_score,
            visual_score=visual_score,
            symmetry_score=symmetry_score,
            available=available,
        )
        _CACHE.set(cache_key, result)
        return result

