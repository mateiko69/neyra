from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.core.security import verify_password
from app.models.analytics_event import AnalyticsEvent
from app.models.device_token import DeviceToken
from app.models.match import Match
from app.models.message import Message
from app.models.message_reaction import MessageReaction
from app.models.oauth_account import OAuthAccount
from app.models.profile import Profile
from app.models.subscription import Subscription
from app.models.swipe import Swipe
from app.models.thread_read_state import ThreadReadState
from app.models.user import User
from app.models.user_block import UserBlock
from app.models.user_ignore import UserIgnore
from app.models.user_report import UserReport
from app.services.analytics import track_event
from app.services.storage.service import get_storage_provider

router = APIRouter()

def _split_csv(value: str | None) -> list[str]:
    return [p.strip() for p in (value or "").split(",") if p.strip()]

def _assume_utc(dt: datetime | None) -> datetime | None:
    """
    SQLite commonly returns naive datetimes even when the column is timezone=True.
    Treat naive values as UTC for comparisons in application logic.
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


def hard_delete_user_id(db: Session, user_id: int) -> None:
    """
    Irreversibly hard-delete a user and most related rows.
    Used by the purge script for expired soft-deletes.
    """
    user_id = int(user_id)
    # Collect media URLs first (before deleting rows).
    profile = db.query(Profile).filter(Profile.user_id == user_id).first()
    photo_urls: list[str] = _split_csv(getattr(profile, "photo_urls", "") if profile else "")
    selfie_url = str(getattr(profile, "verification_selfie_url", "") or "").strip() if profile else ""
    if selfie_url:
        photo_urls.append(selfie_url)

    voice_urls = [
        str(r[0])
        for r in db.query(Message.voice_url)
        .filter(or_(Message.sender_id == user_id, Message.receiver_id == user_id))
        .filter(Message.voice_url.isnot(None))
        .all()
        if r and r[0]
    ]

    provider = get_storage_provider()

    try:
        msg_ids = [
            int(r[0])
            for r in db.query(Message.id)
            .filter(or_(Message.sender_id == user_id, Message.receiver_id == user_id))
            .all()
            if r and r[0]
        ]
        if msg_ids:
            db.query(MessageReaction).filter(
                or_(MessageReaction.user_id == user_id, MessageReaction.message_id.in_(msg_ids))
            ).delete(synchronize_session=False)
        else:
            db.query(MessageReaction).filter(MessageReaction.user_id == user_id).delete(synchronize_session=False)

        db.query(Message).filter(or_(Message.sender_id == user_id, Message.receiver_id == user_id)).delete(synchronize_session=False)
        db.query(ThreadReadState).filter(
            or_(ThreadReadState.user_id == user_id, ThreadReadState.partner_user_id == user_id)
        ).delete(synchronize_session=False)
        db.query(Match).filter(or_(Match.user_a_id == user_id, Match.user_b_id == user_id)).delete(synchronize_session=False)
        db.query(Swipe).filter(or_(Swipe.swiper_id == user_id, Swipe.target_user_id == user_id)).delete(synchronize_session=False)
        db.query(UserBlock).filter(or_(UserBlock.blocker_id == user_id, UserBlock.blocked_id == user_id)).delete(synchronize_session=False)
        db.query(UserIgnore).filter(or_(UserIgnore.user_id == user_id, UserIgnore.ignored_user_id == user_id)).delete(synchronize_session=False)
        db.query(UserReport).filter(or_(UserReport.reporter_id == user_id, UserReport.reported_user_id == user_id)).delete(synchronize_session=False)
        db.query(Subscription).filter(Subscription.user_id == user_id).delete(synchronize_session=False)
        db.query(DeviceToken).filter(DeviceToken.user_id == user_id).delete(synchronize_session=False)
        db.query(OAuthAccount).filter(OAuthAccount.user_id == user_id).delete(synchronize_session=False)
        db.query(AnalyticsEvent).filter(AnalyticsEvent.user_id == user_id).update({"user_id": None}, synchronize_session=False)
        db.query(Profile).filter(Profile.user_id == user_id).delete(synchronize_session=False)
        db.query(User).filter(User.id == user_id).delete(synchronize_session=False)

        db.commit()
    except Exception:
        db.rollback()
        raise

    for url in photo_urls:
        try:
            provider.delete(url)
        except Exception:
            pass
    for url in voice_urls:
        try:
            provider.delete(url)
        except Exception:
            pass


@router.delete("/account")
def delete_account(
    payload: dict[str, Any] = Body(default={}),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Soft-delete the current user's account (reversible for 30 days).
    Account becomes inaccessible immediately (except restore), and is hidden from matching surfaces.
    """
    confirm = bool(payload.get("confirm") is True)
    if not confirm:
        raise HTTPException(status_code=400, detail="Confirmation required")

    # Optional safety: require password re-entry for email/password accounts.
    if current_user.hashed_password:
        pw = str(payload.get("password") or "").strip()
        if not pw:
            raise HTTPException(status_code=400, detail="Password required")
        if not verify_password(pw, current_user.hashed_password):
            raise HTTPException(status_code=401, detail="Invalid password")

    user_id = int(current_user.id)
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    now = datetime.now(UTC)
    scheduled = now + timedelta(days=30)

    if bool(getattr(user, "is_deleted", False)):
        # Idempotent: return current schedule.
        return {
            "ok": True,
            "is_deleted": True,
            "deleted_at": getattr(user, "deleted_at", None).isoformat() if getattr(user, "deleted_at", None) else now.isoformat(),
            "deletion_scheduled_for": getattr(user, "deletion_scheduled_for", None).isoformat() if getattr(user, "deletion_scheduled_for", None) else scheduled.isoformat(),
        }

    track_event(db, "account_delete_started", user_id=user_id, payload={})

    user.is_deleted = True
    user.deleted_at = now
    user.deletion_scheduled_for = scheduled
    db.add(user)

    # Best-effort: revoke device tokens so push + background updates stop immediately.
    db.query(DeviceToken).filter(DeviceToken.user_id == user_id).delete(synchronize_session=False)

    db.commit()

    track_event(db, "account_deleted_scheduled", user_id=user_id, payload={"deletion_scheduled_for": scheduled.isoformat()})
    return {
        "ok": True,
        "is_deleted": True,
        "deleted_at": now.isoformat(),
        "deletion_scheduled_for": scheduled.isoformat(),
    }


@router.post("/account/restore")
def restore_account(
    payload: dict[str, Any] = Body(default={}),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Restore a soft-deleted account within the 30-day window.
    """
    confirm = bool(payload.get("confirm") is True)
    if not confirm:
        raise HTTPException(status_code=400, detail="Confirmation required")

    user_id = int(current_user.id)
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if not bool(getattr(user, "is_deleted", False)):
        return {"ok": True, "restored": False}

    scheduled = getattr(user, "deletion_scheduled_for", None)
    now = datetime.now(UTC)
    scheduled_utc = _assume_utc(scheduled)
    if scheduled_utc is not None and now > scheduled_utc:
        raise HTTPException(status_code=410, detail="Restore window expired")

    user.is_deleted = False
    user.deleted_at = None
    user.deletion_scheduled_for = None
    db.add(user)
    db.commit()
    track_event(db, "account_restored", user_id=user_id, payload={})
    return {"ok": True, "restored": True}

