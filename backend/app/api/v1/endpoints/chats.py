"""Chat thread deletion (match + messages) for authenticated users."""

from __future__ import annotations

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session
from fastapi import APIRouter, Depends, HTTPException

from app.api.api_errors import api_error
from app.api.deps import get_db, get_current_user
from app.models.user import User
from app.models.match import Match
from app.models.message import Message
from app.models.message_reaction import MessageReaction
from app.models.thread_read_state import ThreadReadState
from app.services.ai.cache import bump_user_cache_version

router = APIRouter()


@router.delete("/{match_id}")
def delete_chat(
    match_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if match_id < 1:
        raise HTTPException(status_code=400, detail=api_error("chat.invalid_match"))

    row = db.query(Match).filter(Match.id == int(match_id)).first()
    if not row:
        raise HTTPException(status_code=404, detail=api_error("chat.match_not_found"))

    uid = int(current_user.id)
    if int(row.user_a_id) != uid and int(row.user_b_id) != uid:
        raise HTTPException(status_code=403, detail=api_error("chat.match_forbidden"))

    partner_id = int(row.user_b_id) if int(row.user_a_id) == uid else int(row.user_a_id)

    msg_filter = or_(
        and_(Message.sender_id == uid, Message.receiver_id == partner_id),
        and_(Message.sender_id == partner_id, Message.receiver_id == uid),
    )
    msg_ids = [int(r[0]) for r in db.query(Message.id).filter(msg_filter).all() if r and r[0]]
    if msg_ids:
        db.query(MessageReaction).filter(MessageReaction.message_id.in_(msg_ids)).delete(synchronize_session=False)
    db.query(Message).filter(msg_filter).delete(synchronize_session=False)

    db.query(ThreadReadState).filter(
        or_(
            and_(ThreadReadState.user_id == uid, ThreadReadState.partner_user_id == partner_id),
            and_(ThreadReadState.user_id == partner_id, ThreadReadState.partner_user_id == uid),
        )
    ).delete(synchronize_session=False)

    db.delete(row)
    db.commit()

    bump_user_cache_version("discover_feed", uid)
    return {"ok": True}
