from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.api.api_errors import api_error
from app.api.deps import get_db
from app.api.deps import get_current_user
from app.models.profile import Profile
from app.models.user import User
from app.services.storage.upload_utils import (
    persist_user_image,
    persist_user_voice_note,
    read_validate_audio,
    read_validate_image,
)

router = APIRouter()
log = logging.getLogger(__name__)

_MAX_FILES_BATCH = 12


def _split_csv_urls(value: str | None) -> list[str]:
    return [p.strip() for p in (value or "").split(",") if p.strip()]


def _join_csv_urls(values: list[str]) -> str:
    return ",".join([v.strip() for v in values if v and v.strip()])


def _persist_profile_photo_url(db: Session, user_id: int, url: str, *, max_photos: int = 6) -> str:
    if not (url or "").strip():
        log.warning("persist_profile_photo_url skipped empty url user_id=%s", user_id)
        profile = db.query(Profile).filter(Profile.user_id == user_id).first()
        return (getattr(profile, "photo_urls", "") or "") if profile else ""
    profile = db.query(Profile).filter(Profile.user_id == user_id).first()
    if not profile:
        # Minimal profile to keep uploads consistent; other fields can be filled later.
        profile = Profile(user_id=user_id, display_name="User")
        db.add(profile)
        db.flush()
    existing = _split_csv_urls(getattr(profile, "photo_urls", "") or "")
    if url not in existing:
        existing.append(url)
    # Cap list to avoid unbounded growth from repeated uploads
    existing = existing[:max_photos]
    profile.photo_urls = _join_csv_urls(existing)
    db.add(profile)
    db.commit()
    db.refresh(profile)
    return profile.photo_urls or ""


@router.post("/photo")
async def upload_photo(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    log.info(
        "upload_photo start user_id=%s filename=%s content_type=%s",
        current_user.id,
        file.filename,
        file.content_type,
    )
    content, ext = await read_validate_image(file)
    url = persist_user_image(current_user.id, ext, content)
    if not (url or "").strip():
        log.error(
            "upload_photo storage_unavailable user_id=%s — configure S3/R2 in production",
            current_user.id,
        )
        raise HTTPException(
            status_code=503,
            detail=api_error(
                "upload.storage_unavailable",
                message="Object storage is not configured. For production, set S3_BUCKET, S3_ACCESS_KEY_ID, S3_SECRET_ACCESS_KEY, S3_PUBLIC_BASE_URL, and optional S3_ENDPOINT_URL (R2).",
            ),
        )
    saved_csv = _persist_profile_photo_url(db, current_user.id, url)
    log.info("upload_photo ok user_id=%s url=%s saved_photo_urls=%s", current_user.id, url, saved_csv)
    return {"url": url}


@router.post("/photos")
async def upload_photos(
    files: list[UploadFile] = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not files:
        raise HTTPException(status_code=400, detail=api_error("upload.no_files"))
    if len(files) > _MAX_FILES_BATCH:
        log.warning("upload_photos rejected: batch too large count=%s max=%s", len(files), _MAX_FILES_BATCH)
        raise HTTPException(
            status_code=400,
            detail=api_error("upload.too_many_files", max=_MAX_FILES_BATCH),
        )
    urls: list[str] = []
    for i, f in enumerate(files):
        try:
            content, ext = await read_validate_image(f)
            u = persist_user_image(current_user.id, ext, content)
            if not (u or "").strip():
                log.error(
                    "upload_photos storage_unavailable user_id=%s index=%s",
                    current_user.id,
                    i + 1,
                )
                raise HTTPException(
                    status_code=503,
                    detail=api_error(
                        "upload.storage_unavailable",
                        message="Object storage is not configured. For production, set S3_BUCKET, S3_ACCESS_KEY_ID, S3_SECRET_ACCESS_KEY, S3_PUBLIC_BASE_URL, and optional S3_ENDPOINT_URL (R2).",
                    ),
                )
            urls.append(u)
        except HTTPException as e:
            if e.status_code == 503:
                raise
            inner = e.detail if isinstance(e.detail, dict) else {}
            code = inner.get("code") if isinstance(inner, dict) else None
            log.warning(
                "upload_photos item failed index=%s user_id=%s inner_code=%s",
                i + 1,
                current_user.id,
                code,
            )
            raise HTTPException(
                status_code=e.status_code,
                detail=api_error("upload.item_failed", part=i + 1),
            ) from None
    saved = ""
    for u in urls:
        saved = _persist_profile_photo_url(db, current_user.id, u)
    return {"urls": urls}


@router.post("/voice")
async def upload_voice(file: UploadFile = File(...), current_user: User = Depends(get_current_user)):
    log.info(
        "upload_voice start user_id=%s filename=%s content_type=%s",
        current_user.id,
        file.filename,
        file.content_type,
    )
    content, ct = await read_validate_audio(file)
    url = persist_user_voice_note(current_user.id, ct, content)
    if not (url or "").strip():
        log.error(
            "upload_voice storage_unavailable user_id=%s — configure S3/R2 in production",
            current_user.id,
        )
        raise HTTPException(
            status_code=503,
            detail=api_error(
                "upload.storage_unavailable",
                message="Object storage is not configured. For production, set S3_BUCKET, S3_ACCESS_KEY_ID, S3_SECRET_ACCESS_KEY, S3_PUBLIC_BASE_URL, and optional S3_ENDPOINT_URL (R2).",
            ),
        )
    # Duration is computed client-side; return null here to keep backend dependency-free.
    log.info("upload_voice ok user_id=%s url=%s bytes=%s ct=%s", current_user.id, url, len(content), ct)
    return {"url": url, "content_type": ct, "bytes": len(content), "duration_ms": None}
