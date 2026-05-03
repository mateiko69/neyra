from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.models.match import Match
from app.models.profile import Profile
from app.models.swipe import Swipe
from app.models.user import User
from app.services.analytics import track_event
from app.services.demo_behavior import schedule_demo_first_message_maybe
from app.services.demo_mode import ensure_demo_profiles, is_demo_mode_enabled, is_demo_profile
from app.services.events import publish_event
from app.services.safety import is_blocked
from app.services.starter_match import (
    count_matches_for_user,
    first_demo_profile_for_starter,
    newest_match_for_user,
    partner_user_id_from_match,
    pick_ranked_starter_candidate,
)
from app.services.ai.cache import bump_user_cache_version
from app.utils.media_urls import normalize_photo_url

router = APIRouter()


def _quick_match_json(db: Session, partner_profile: Profile, match: Match) -> dict:
    display_name = str(getattr(partner_profile, "display_name", "") or "").strip()
    photo_urls = str(getattr(partner_profile, "photo_urls", "") or "").strip()
    first_raw = photo_urls.split(",")[0].strip() if photo_urls else ""
    first_photo = None
    if first_raw:
        first_photo = normalize_photo_url(first_raw, demo_profile_gender=getattr(partner_profile, "gender", None)) or None
    return {
        "match_id": int(match.id),
        "partner_user_id": int(partner_profile.user_id),
        "partner_name": display_name,
        "partner_photo_url": first_photo,
    }


def _ensure_mutual_likes_and_match(
    db: Session,
    current_user_id: int,
    partner_user_id: int,
    *,
    had_any_match_before: bool,
) -> Match:
    a, b = sorted([int(current_user_id), int(partner_user_id)])
    match = db.query(Match).filter(Match.user_a_id == a, Match.user_b_id == b).first()
    if match:
        return match

    for swiper_id, target_id in [(int(current_user_id), partner_user_id), (partner_user_id, int(current_user_id))]:
        row = db.query(Swipe).filter(Swipe.swiper_id == swiper_id, Swipe.target_user_id == target_id).first()
        if not row:
            db.add(Swipe(swiper_id=swiper_id, target_user_id=target_id, liked=True))
        else:
            if not bool(getattr(row, "liked", False)):
                row.liked = True
                db.add(row)
    db.commit()

    match = Match(user_a_id=a, user_b_id=b)
    db.add(match)
    db.commit()
    db.refresh(match)
    publish_event("match_created", {"match_id": match.id, "user_a_id": a, "user_b_id": b})
    if not had_any_match_before:
        track_event(
            db,
            "first_match_created",
            user_id=int(current_user_id),
            payload={"match_id": match.id, "partner_user_id": int(partner_user_id), "source": "onboarding_quick_match"},
        )
    return match


@router.post("/quick-match")
def quick_match(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """
    Onboarding: ensure the user can reach a first match quickly.

    - If they already have at least one match, return the newest one (idempotent for the client).
    - If they have zero matches: pick the top compatibility-ranked real profile (Discover-style filters),
      create mutual likes + Match (no swipe probability gate), or fall back to a demo profile when needed.
    """
    uid = int(current_user.id)
    my_profile = db.query(Profile).filter(Profile.user_id == uid).first()

    existing_n = count_matches_for_user(db, uid)
    if existing_n > 0:
        row = newest_match_for_user(db, uid)
        if not row:
            raise HTTPException(status_code=404, detail="No match found")
        pid = partner_user_id_from_match(row, uid)
        partner_profile = db.query(Profile).filter(Profile.user_id == pid).first()
        partner_user = db.query(User).filter(User.id == pid).first()
        if not partner_profile or not partner_user or bool(getattr(partner_user, "is_deleted", False)):
            raise HTTPException(status_code=404, detail="Match partner unavailable")
        track_event(
            db,
            "onboarding_quick_match_reused",
            user_id=uid,
            payload={"match_id": int(row.id), "partner_user_id": int(pid)},
        )
        return _quick_match_json(db, partner_profile, row)

    partner_profile: Profile | None = pick_ranked_starter_candidate(db, uid, my_profile)

    source = "real_ranked"
    if partner_profile is None and is_demo_mode_enabled(db):
        partner_profile = first_demo_profile_for_starter(db)
        source = "demo_preferred"

    if partner_profile is None:
        try:
            ensure_demo_profiles(db)
        except Exception:
            pass
        partner_profile = first_demo_profile_for_starter(db)
        if partner_profile:
            source = "demo_seeded"

    if not partner_profile:
        raise HTTPException(status_code=404, detail="No profiles available")

    partner_user_id = int(partner_profile.user_id)
    if partner_user_id == uid:
        raise HTTPException(status_code=400, detail="Cannot match yourself")
    if is_blocked(db, uid, partner_user_id):
        raise HTTPException(status_code=403, detail="User is blocked")

    partner_user = db.query(User).filter(User.id == partner_user_id).first()
    if not partner_user or bool(getattr(partner_user, "is_deleted", False)):
        raise HTTPException(status_code=404, detail="Partner not found")

    match = _ensure_mutual_likes_and_match(db, uid, partner_user_id, had_any_match_before=False)
    track_event(
        db,
        "onboarding_quick_match_created",
        user_id=uid,
        payload={"match_id": int(match.id), "partner_user_id": partner_user_id, "source": source},
    )
    bump_user_cache_version("discover_feed", uid)
    bump_user_cache_version("discover_feed", partner_user_id)

    if is_demo_profile(partner_profile, partner_user):
        schedule_demo_first_message_maybe(db, partner_user_id, uid)

    return _quick_match_json(db, partner_profile, match)
