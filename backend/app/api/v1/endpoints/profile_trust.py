from __future__ import annotations

from sqlalchemy.orm import Session
from fastapi import APIRouter, Depends, Query

from app.api.deps import get_db, get_current_user
from app.models.user import User
from app.models.profile import Profile
from app.services.trust.profile_trust_score import compute_profile_trust
from app.services.trust.profile_quality import compute_profile_quality
from app.services.ai.cache import get_redis
from app.services.analytics import track_event

router = APIRouter()


@router.get("/profile/trust")
def profile_trust(
    user_id: int | None = Query(default=None, ge=1),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    target_user_id = int(user_id) if user_id else int(current_user.id)
    profile = db.query(Profile).filter(Profile.user_id == target_user_id).first()
    trust = compute_profile_trust(profile)
    quality = compute_profile_quality(profile)
    # Best-effort analytics for low-quality detection (deduped via Redis, fail-open).
    if quality.quality_flag == "low_quality" and profile:
        try:
            r = get_redis()
            key = f"trust:lq:{profile.user_id}:{__import__('datetime').datetime.now(__import__('datetime').UTC).strftime('%Y%m%d')}"
            if r.set(name=key, value="1", nx=True, ex=60 * 60 * 30):
                track_event(db, "low_quality_detected", user_id=profile.user_id, payload={"reason_bucket": quality.quality_reason})
        except Exception:
            pass
    return {
        "trust_score": trust.trust_score,
        "trust_level": trust.trust_level,
        "is_verified": trust.is_verified,
        "quality_flag": quality.quality_flag,
    }

