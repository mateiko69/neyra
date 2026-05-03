from datetime import datetime

from sqlalchemy import func
from sqlalchemy.orm import Session
from fastapi import APIRouter, Depends
from app.api.deps import get_db, get_current_user
from app.models.user import User
from app.models.match import Match
from app.models.message import Message
from app.models.thread_read_state import ThreadReadState
from app.services.safety import blocked_user_ids
from app.api.v1.endpoints.likes import count_eligible_incoming_likes

router = APIRouter()


@router.get("/badges")
def nav_badges(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    blocked = blocked_user_ids(db, current_user.id)
    match_rows = (
        db.query(Match)
        .filter((Match.user_a_id == current_user.id) | (Match.user_b_id == current_user.id))
        .all()
    )
    visible_match_rows = []
    partner_ids = []
    for row in match_rows:
        pid = row.user_b_id if row.user_a_id == current_user.id else row.user_a_id
        if blocked and pid in blocked:
            continue
        visible_match_rows.append(row)
        partner_ids.append(pid)
    partner_ids = list(dict.fromkeys(partner_ids))

    # Avoid N+1: compute unread counts with one aggregate query.
    # Unread = messages sent to current_user after last_read_at (per partner thread).
    unread_messages = 0
    chat_threads_unread = 0
    if partner_ids:
        # Join incoming messages to read state (per partner thread).
        # If no read state exists, treat as "never read" -> unread all incoming messages.
        epoch = datetime(1970, 1, 1)
        m = Message
        r = ThreadReadState
        unread_filter = m.created_at > func.coalesce(r.last_read_at, epoch)
        unread_messages = int(
            (
                db.query(func.count(m.id))
                .outerjoin(r, (r.user_id == current_user.id) & (r.partner_user_id == m.sender_id))
                .filter(m.receiver_id == current_user.id)
                .filter(m.sender_id.in_(partner_ids))
                .filter(unread_filter)
                .scalar()
                or 0
            )
        )
        chat_threads_unread = int(
            (
                db.query(func.count(func.distinct(m.sender_id)))
                .outerjoin(r, (r.user_id == current_user.id) & (r.partner_user_id == m.sender_id))
                .filter(m.receiver_id == current_user.id)
                .filter(m.sender_id.in_(partner_ids))
                .filter(unread_filter)
                .scalar()
                or 0
            )
        )

    u = db.query(User).filter(User.id == current_user.id).first()
    new_matches = 0
    if u is not None:
        if u.matches_last_seen_at is None:
            new_matches = len(visible_match_rows)
        else:
            new_matches = sum(1 for row in visible_match_rows if row.created_at and row.created_at > u.matches_last_seen_at)

    incoming_likes = int(count_eligible_incoming_likes(db, int(current_user.id)))
    matches_total = len(visible_match_rows)
    matches_attention = int(incoming_likes) + int(new_matches)

    return {
        "unread_messages": unread_messages,
        "chat_threads_unread": chat_threads_unread,
        "new_matches": new_matches,
        "incoming_likes": incoming_likes,
        "matches": matches_total,
        "matches_attention": matches_attention,
    }
