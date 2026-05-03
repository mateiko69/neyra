from __future__ import annotations

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.match import Match
from app.models.user_block import UserBlock
from app.models.user_ignore import UserIgnore


def is_blocked(db: Session, user_a: int, user_b: int) -> bool:
    """True if either user blocked the other."""
    if not user_a or not user_b or user_a == user_b:
        return False
    return (
        db.query(UserBlock)
        .filter(
            or_(
                (UserBlock.blocker_id == user_a) & (UserBlock.blocked_id == user_b),
                (UserBlock.blocker_id == user_b) & (UserBlock.blocked_id == user_a),
            )
        )
        .first()
        is not None
    )


def blocked_user_ids(db: Session, user_id: int) -> set[int]:
    """All user ids that should be hidden from user_id due to blocks (either direction)."""
    if not user_id:
        return set()
    rows = (
        db.query(UserBlock.blocker_id, UserBlock.blocked_id)
        .filter(or_(UserBlock.blocker_id == user_id, UserBlock.blocked_id == user_id))
        .all()
    )
    out: set[int] = set()
    for blocker_id, blocked_id in rows:
        if blocker_id == user_id and blocked_id:
            out.add(int(blocked_id))
        elif blocked_id == user_id and blocker_id:
            out.add(int(blocker_id))
    return out


def ignored_user_ids(db: Session, user_id: int) -> set[int]:
    if not user_id:
        return set()
    rows = db.query(UserIgnore.ignored_user_id).filter(UserIgnore.user_id == user_id).all()
    return {int(r[0]) for r in rows if r and r[0]}


def remove_match_between_users(db: Session, user_a: int, user_b: int) -> bool:
    """Delete the match row for a user pair if it exists."""
    if not user_a or not user_b or user_a == user_b:
        return False
    a, b = sorted([int(user_a), int(user_b)])
    deleted = (
        db.query(Match)
        .filter(Match.user_a_id == a, Match.user_b_id == b)
        .delete(synchronize_session=False)
    )
    return bool(deleted)
