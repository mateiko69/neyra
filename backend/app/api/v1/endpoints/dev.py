from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.core.config import settings
from sqlalchemy import or_

from app.models.incoming_like_hide import IncomingLikeHide
from app.models.match import Match
from app.models.message import Message
from app.models.profile import Profile
from app.models.swipe import Swipe
from app.models.thread_read_state import ThreadReadState
from app.models.user import User
from app.api.v1.endpoints.discover import discover_candidate_debug_breakdown
from app.services.ai.cache import bump_user_cache_version

router = APIRouter()


def _ensure_dev_tools() -> None:
    if not bool(getattr(settings, "DEV_TOOLS_ENABLED", False)):
        raise HTTPException(status_code=403, detail={"error": "dev_tools_disabled"})


@router.post("/reset-swipes")
def reset_swipes(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Dev-only: clear swipes/matches/likes for the current user to re-test Discover quickly."""
    _ensure_dev_tools()
    uid = int(current_user.id)
    swipes_deleted = int(
        db.query(Swipe)
        .filter((Swipe.swiper_id == uid) | (Swipe.target_user_id == uid))
        .delete(synchronize_session=False)
        or 0
    )
    matches_deleted = int(
        db.query(Match).filter((Match.user_a_id == uid) | (Match.user_b_id == uid)).delete(synchronize_session=False) or 0
    )
    hides_deleted = int(
        db.query(IncomingLikeHide).filter(IncomingLikeHide.viewer_user_id == uid).delete(synchronize_session=False) or 0
    )
    db.commit()
    bump_user_cache_version("discover_feed", uid)
    return {
        "ok": True,
        "swipes_deleted": swipes_deleted,
        "matches_deleted": matches_deleted,
        "incoming_like_hides_deleted": hides_deleted,
    }


@router.post("/reset-match-state")
def reset_match_state(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Dev-only: clear swipes, likes visibility, matches, chat threads, and messages for the current user."""
    _ensure_dev_tools()
    uid = int(current_user.id)
    messages_deleted = int(
        db.query(Message)
        .filter(or_(Message.sender_id == uid, Message.receiver_id == uid))
        .delete(synchronize_session=False)
        or 0
    )
    read_states_deleted = int(
        db.query(ThreadReadState)
        .filter(or_(ThreadReadState.user_id == uid, ThreadReadState.partner_user_id == uid))
        .delete(synchronize_session=False)
        or 0
    )
    swipes_deleted = int(
        db.query(Swipe)
        .filter(or_(Swipe.swiper_id == uid, Swipe.target_user_id == uid))
        .delete(synchronize_session=False)
        or 0
    )
    matches_deleted = int(
        db.query(Match).filter(or_(Match.user_a_id == uid, Match.user_b_id == uid)).delete(synchronize_session=False) or 0
    )
    hides_deleted = int(
        db.query(IncomingLikeHide)
        .filter(or_(IncomingLikeHide.viewer_user_id == uid, IncomingLikeHide.admirer_user_id == uid))
        .delete(synchronize_session=False)
        or 0
    )
    db.commit()
    bump_user_cache_version("discover_feed", uid)
    return {
        "ok": True,
        "messages_deleted": messages_deleted,
        "thread_read_states_deleted": read_states_deleted,
        "swipes_deleted": swipes_deleted,
        "matches_deleted": matches_deleted,
        "incoming_like_hides_deleted": hides_deleted,
    }


@router.get("/discover-candidate-debug")
def discover_candidate_debug(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Dev-only: explain real-profile Discover eligibility for the current viewer."""
    _ensure_dev_tools()
    viewer_id = int(current_user.id)
    rows = (
        db.query(User, Profile)
        .join(Profile, Profile.user_id == User.id)
        .filter(User.id != viewer_id)
        .filter(User.is_demo.is_(False))
        .filter((Profile.is_demo_profile.is_(False)) | (Profile.is_demo_profile.is_(None)))
        .order_by(User.id.asc())
        .all()
    )
    candidates = [
        discover_candidate_debug_breakdown(
            db,
            viewer=current_user,
            candidate_user=user,
            candidate_profile=profile,
        )
        for user, profile in rows
    ]
    return {
        "viewer_user_id": viewer_id,
        "candidate_count": len(candidates),
        "candidates": candidates,
    }


@router.get("/discover-pair-debug")
def discover_pair_debug(
    other_user_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _ensure_dev_tools()
    viewer = db.query(User).filter(User.id == int(current_user.id)).first()
    other = db.query(User).filter(User.id == int(other_user_id)).first()
    if not viewer or not other:
        raise HTTPException(status_code=404, detail={"error": "user_not_found"})
    viewer_profile = db.query(Profile).filter(Profile.user_id == int(viewer.id)).first()
    other_profile = db.query(Profile).filter(Profile.user_id == int(other.id)).first()
    if not viewer_profile or not other_profile:
        raise HTTPException(status_code=404, detail={"error": "profile_not_found"})
    a = discover_candidate_debug_breakdown(
        db,
        viewer=viewer,
        candidate_user=other,
        candidate_profile=other_profile,
    )
    b = discover_candidate_debug_breakdown(
        db,
        viewer=other,
        candidate_user=viewer,
        candidate_profile=viewer_profile,
    )
    a_reasons = list(a.get("excluded_reasons") or [])
    b_reasons = list(b.get("excluded_reasons") or [])
    return {
        "current_user": a,
        "other_user": b,
        "should_see_each_other": bool(not a_reasons and not b_reasons),
        "reasons_current_cannot_see_other": a_reasons,
        "reasons_other_cannot_see_current": b_reasons,
    }


@router.post("/reset-dating-state")
def reset_dating_state(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Dev-only reset for organic matching tests. Keeps profile/photos."""
    _ensure_dev_tools()
    uid = int(current_user.id)
    messages_deleted = int(
        db.query(Message).filter(or_(Message.sender_id == uid, Message.receiver_id == uid)).delete(synchronize_session=False) or 0
    )
    thread_read_states_deleted = int(
        db.query(ThreadReadState)
        .filter(or_(ThreadReadState.user_id == uid, ThreadReadState.partner_user_id == uid))
        .delete(synchronize_session=False)
        or 0
    )
    swipes_deleted = int(
        db.query(Swipe).filter(or_(Swipe.swiper_id == uid, Swipe.target_user_id == uid)).delete(synchronize_session=False) or 0
    )
    likes_deleted = int(swipes_deleted)
    matches_deleted = int(
        db.query(Match).filter(or_(Match.user_a_id == uid, Match.user_b_id == uid)).delete(synchronize_session=False) or 0
    )
    hides_deleted = int(
        db.query(IncomingLikeHide)
        .filter(or_(IncomingLikeHide.viewer_user_id == uid, IncomingLikeHide.admirer_user_id == uid))
        .delete(synchronize_session=False)
        or 0
    )
    db.commit()
    bump_user_cache_version("discover_feed", uid)
    return {
        "ok": True,
        "swipes_deleted": swipes_deleted,
        "likes_deleted": likes_deleted,
        "matches_deleted": matches_deleted,
        "messages_deleted": messages_deleted,
        "thread_read_states_deleted": thread_read_states_deleted,
        "incoming_like_hides_deleted": hides_deleted,
    }
