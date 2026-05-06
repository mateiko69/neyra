"""Authenticated profile gallery (/api/v1/profile/photos)."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.api_errors import api_error
from app.api.deps import get_current_user
from app.api.deps import get_db
from app.models.profile import Profile
from app.models.user import User
from app.services.ai.cache import bump_user_cache_version
from app.services.profile_photos_service import (
    append_uploaded_photo_url,
    csv_from_ordered_rows,
    delete_photo,
    ensure_rows_from_profile_csv,
    ordered_rows,
    refresh_visual_embedding_best_effort,
    rows_to_public_payload,
    set_primary_photo,
)
from app.services.storage.service import uploads_are_available
from app.services.storage.upload_utils import persist_user_image, read_validate_image

router = APIRouter()
log = logging.getLogger(__name__)


class ProfilePhotoItem(BaseModel):
    id: int
    url: str
    is_primary: bool


class PhotoMutationPayload(BaseModel):
    photos: list[ProfilePhotoItem]
    photo_urls: str


def _gallery_profile_or_404(db: Session, user: User) -> Profile:
    profile = db.query(Profile).filter(Profile.user_id == user.id).first()
    if not profile:
        raise HTTPException(status_code=404, detail=api_error("profile.not_found"))
    return profile


@router.get("/photos", response_model=list[ProfilePhotoItem])
def list_my_photos(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    profile = _gallery_profile_or_404(db, current_user)
    rows = ordered_rows(db, current_user.id)
    if not rows and (profile.photo_urls or "").strip():
        rows = ensure_rows_from_profile_csv(db, profile)
    if not rows:
        return []
    return [ProfilePhotoItem(**x) for x in rows_to_public_payload(rows)]


@router.post("/photos", response_model=PhotoMutationPayload)
async def upload_my_photo(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not uploads_are_available():
        raise HTTPException(
            status_code=503,
            detail=api_error(
                "upload.storage_unavailable",
                message="Object storage is not configured. Set S3_ENDPOINT_URL, S3_ACCESS_KEY_ID, "
                "S3_SECRET_ACCESS_KEY, S3_BUCKET_NAME or S3_BUCKET, S3_PUBLIC_BASE_URL "
                "(and optional S3_REGION=auto for R2).",
            ),
        )
    profile = _gallery_profile_or_404(db, current_user)
    content, ext = await read_validate_image(file)
    url = persist_user_image(current_user.id, ext, content)
    if not (url or "").strip():
        raise HTTPException(status_code=503, detail=api_error("upload.storage_unavailable"))
    append_uploaded_photo_url(db, profile, url)
    profile = _gallery_profile_or_404(db, current_user)
    refresh_visual_embedding_best_effort(profile)
    db.add(profile)
    db.commit()
    rows = ordered_rows(db, current_user.id)
    bump_user_cache_version("discover_feed", int(current_user.id))
    log.info("profile_photo_uploaded user_id=%s", current_user.id)
    return PhotoMutationPayload(
        photos=[ProfilePhotoItem(**x) for x in rows_to_public_payload(rows)],
        photo_urls=csv_from_ordered_rows(rows),
    )


@router.delete("/photos/{photo_id}")
def delete_my_photo(
    photo_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    profile = _gallery_profile_or_404(db, current_user)
    if photo_id < 1:
        raise HTTPException(status_code=404, detail=api_error("profile.photo.not_found"))
    delete_photo(db, profile, photo_id)
    profile = _gallery_profile_or_404(db, current_user)
    refresh_visual_embedding_best_effort(profile)
    db.add(profile)
    db.commit()
    bump_user_cache_version("discover_feed", int(current_user.id))
    return {"ok": True}


@router.post("/photos/{photo_id}/primary", response_model=PhotoMutationPayload)
def set_my_primary_photo(
    photo_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    profile = _gallery_profile_or_404(db, current_user)
    if photo_id < 1:
        raise HTTPException(status_code=404, detail=api_error("profile.photo.not_found"))
    set_primary_photo(db, profile, photo_id)
    profile = _gallery_profile_or_404(db, current_user)
    refresh_visual_embedding_best_effort(profile)
    db.add(profile)
    db.commit()
    rows = ordered_rows(db, current_user.id)
    bump_user_cache_version("discover_feed", int(current_user.id))
    return PhotoMutationPayload(
        photos=[ProfilePhotoItem(**x) for x in rows_to_public_payload(rows)],
        photo_urls=csv_from_ordered_rows(rows),
    )
