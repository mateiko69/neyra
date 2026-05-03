from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.api_errors import api_error
from app.api.deps import get_current_user, get_db
from app.models.user import User
from app.models.user_block import UserBlock
from app.models.user_ignore import UserIgnore
from app.models.user_report import UserReport
from app.services.safety import is_blocked, remove_match_between_users
from app.services.ai.cache import bump_user_cache_version
from app.services.demo_mode import is_demo_user_id

router = APIRouter()
legacy_router = APIRouter()

REPORT_REASON_MAX_LENGTH = 255


def _parse_target_user_id(payload: dict) -> int:
    try:
        return int(payload.get("user_id") or 0)
    except (TypeError, ValueError):
        return 0


def _ensure_target_user_exists(target_user_id: int, current_user: User, db: Session) -> None:
    if target_user_id < 1 or target_user_id == current_user.id:
        raise HTTPException(status_code=400, detail=api_error("safety.invalid_target"))
    exists = db.query(User.id).filter(User.id == target_user_id).first()
    if exists is None:
        raise HTTPException(status_code=404, detail=api_error("safety.user_not_found"))


def _block_user(target_user_id: int, current_user: User, db: Session) -> dict:
    _ensure_target_user_exists(target_user_id, current_user, db)
    existing = (
        db.query(UserBlock)
        .filter(UserBlock.blocker_id == current_user.id, UserBlock.blocked_id == target_user_id)
        .first()
    )
    match_removed = remove_match_between_users(db, current_user.id, target_user_id)
    if existing:
        if match_removed:
            db.commit()
        return {"ok": True, "blocked": True, "match_removed": match_removed}
    db.add(UserBlock(blocker_id=current_user.id, blocked_id=target_user_id))
    db.commit()
    bump_user_cache_version("discover_feed", int(current_user.id))
    return {"ok": True, "blocked": True, "match_removed": match_removed}


def _unblock_user(target_user_id: int, current_user: User, db: Session) -> dict:
    if target_user_id < 1 or target_user_id == current_user.id:
        raise HTTPException(status_code=400, detail=api_error("safety.invalid_target"))
    existing = (
        db.query(UserBlock)
        .filter(UserBlock.blocker_id == current_user.id, UserBlock.blocked_id == target_user_id)
        .first()
    )
    if existing:
        db.delete(existing)
        db.commit()
    bump_user_cache_version("discover_feed", int(current_user.id))
    return {"ok": True, "blocked": False}


def _ignore_user(target_user_id: int, current_user: User, db: Session) -> dict:
    _ensure_target_user_exists(target_user_id, current_user, db)
    if target_user_id < 1 or target_user_id == current_user.id:
        raise HTTPException(status_code=400, detail=api_error("safety.invalid_target"))
    if is_blocked(db, current_user.id, target_user_id):
        raise HTTPException(status_code=403, detail=api_error("chat.user_blocked"))
    existing = (
        db.query(UserIgnore)
        .filter(UserIgnore.user_id == current_user.id, UserIgnore.ignored_user_id == target_user_id)
        .first()
    )
    if existing:
        return {"ok": True, "ignored": True}
    db.add(UserIgnore(user_id=current_user.id, ignored_user_id=target_user_id))
    db.commit()
    bump_user_cache_version("discover_feed", int(current_user.id))
    return {"ok": True, "ignored": True}


def _unignore_user(target_user_id: int, current_user: User, db: Session) -> dict:
    if target_user_id < 1 or target_user_id == current_user.id:
        raise HTTPException(status_code=400, detail=api_error("safety.invalid_target"))
    existing = (
        db.query(UserIgnore)
        .filter(UserIgnore.user_id == current_user.id, UserIgnore.ignored_user_id == target_user_id)
        .first()
    )
    if existing:
        db.delete(existing)
        db.commit()
    bump_user_cache_version("discover_feed", int(current_user.id))
    return {"ok": True, "ignored": False}


def _report_user(target_user_id: int, reason: str, current_user: User, db: Session) -> dict:
    _ensure_target_user_exists(target_user_id, current_user, db)
    if is_demo_user_id(db, target_user_id):
        raise HTTPException(status_code=400, detail=api_error("safety.demo_report_forbidden"))
    if not reason:
        raise HTTPException(status_code=400, detail=api_error("safety.report_reason_required"))
    if len(reason) > REPORT_REASON_MAX_LENGTH:
        raise HTTPException(status_code=400, detail=api_error("safety.report_reason_too_long"))
    # Parse category from "category: details" (frontend uses that shape).
    raw = (reason or "").strip()
    category = raw.split(":", 1)[0].strip().lower() if ":" in raw else raw.strip().lower()
    if not category:
        category = "other"
    db.add(UserReport(reporter_id=current_user.id, reported_user_id=target_user_id, reason=reason, category=category, status="open"))
    db.commit()
    return {"ok": True}


@router.post("/{user_id}/block")
def block_user(user_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _block_user(user_id, current_user, db)


@router.delete("/{user_id}/block")
def unblock_user(user_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _unblock_user(user_id, current_user, db)


@router.post("/{user_id}/ignore")
def ignore_user(user_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _ignore_user(user_id, current_user, db)


@router.delete("/{user_id}/ignore")
def unignore_user(user_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _unignore_user(user_id, current_user, db)


@router.post("/{user_id}/report")
def report_user(user_id: int, payload: dict, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    reason = str(payload.get("reason") or "").strip()
    return _report_user(user_id, reason, current_user, db)


@legacy_router.post("/block")
def legacy_block_user(payload: dict, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _block_user(_parse_target_user_id(payload), current_user, db)


@legacy_router.delete("/block/{target_user_id}")
def legacy_unblock_user(target_user_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _unblock_user(target_user_id, current_user, db)


@legacy_router.post("/ignore")
def legacy_ignore_user(payload: dict, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _ignore_user(_parse_target_user_id(payload), current_user, db)


@legacy_router.delete("/ignore/{target_user_id}")
def legacy_unignore_user(target_user_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _unignore_user(target_user_id, current_user, db)


@legacy_router.post("/report")
def legacy_report_user(payload: dict, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    target_user_id = _parse_target_user_id(payload)
    reason = str(payload.get("reason") or payload.get("category") or "").strip()
    details = str(payload.get("details") or "").strip()
    if reason and details:
        reason = f"{reason}: {details}"
    elif details and not reason:
        reason = details
    return _report_user(target_user_id, reason, current_user, db)
