"""Canonical mutual-like → Match creation (single pair ordering: min_user_id, max_user_id)."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from app.models.match import Match
from app.models.swipe import Swipe

logger = logging.getLogger(__name__)


def create_match_if_mutual(
    db: Session,
    user_id: int,
    target_user_id: int,
    *,
    action: str = "unknown",
) -> dict[str, Any]:
    """
    After a like from user_id toward target_user_id is persisted, ensure a Match exists
    when both sides have liked=True.

    There is no separate Conversation row; chat threads are keyed by partner user id.
    ``conversation_id`` in the response is the partner's user id for the actor (user_id).
    """
    uid = int(user_id)
    tid = int(target_user_id)
    out: dict[str, Any] = {
        "matched": False,
        "match_id": None,
        "conversation_id": None,
        "match_row_created": False,
    }
    if uid == tid:
        _log_flow(uid, tid, action, False, False, False, None, None)
        return out

    forward = db.query(Swipe).filter(Swipe.swiper_id == uid, Swipe.target_user_id == tid).first()
    reverse = db.query(Swipe).filter(Swipe.swiper_id == tid, Swipe.target_user_id == uid).first()
    existing_like_forward = bool(forward and bool(getattr(forward, "liked", False)))
    existing_like_reverse = bool(reverse and bool(getattr(reverse, "liked", False)))

    if not (existing_like_forward and existing_like_reverse):
        _log_flow(uid, tid, action, existing_like_forward, existing_like_reverse, False, None, None)
        return out

    a, b = sorted([uid, tid])
    match = db.query(Match).filter(Match.user_a_id == a, Match.user_b_id == b).first()
    created = False
    if not match:
        match = Match(user_a_id=a, user_b_id=b)
        db.add(match)
        db.commit()
        db.refresh(match)
        created = True

    partner_for_actor = tid
    _log_flow(uid, tid, action, existing_like_forward, existing_like_reverse, True, int(match.id), partner_for_actor)
    return {
        "matched": True,
        "match_id": int(match.id),
        "conversation_id": int(partner_for_actor),
        "match_row_created": created,
    }


def _log_flow(
    user_id: int,
    target_user_id: int,
    action: str,
    existing_like_forward: bool,
    existing_like_reverse: bool,
    matched: bool,
    match_id: int | None,
    conversation_id: int | None,
) -> None:
    payload = {
        "user_id": user_id,
        "target_user_id": target_user_id,
        "action": action,
        "existing_like_forward": existing_like_forward,
        "existing_like_reverse": existing_like_reverse,
        "matched": matched,
        "match_id": match_id,
        "conversation_id": conversation_id,
    }
    logger.info("match_flow_debug %s", payload)
