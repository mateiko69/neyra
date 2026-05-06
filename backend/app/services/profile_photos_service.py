"""Profile gallery: DB rows + synced `profiles.photo_urls` CSV (legacy compat)."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.api.api_errors import api_error
from app.models.profile import Profile
from app.models.profile_photo import ProfilePhoto
from app.services.storage.service import get_storage_provider
from app.services.visual_embeddings import compute_visual_embedding_from_url
from app.utils.media_urls import normalize_photo_url

MAX_PHOTOS = 6
log = logging.getLogger(__name__)


def csv_from_ordered_rows(rows: list[ProfilePhoto]) -> str:
    return ",".join((r.url or "").strip() for r in rows if (r.url or "").strip())


def ordered_rows(db: Session, user_id: int) -> list[ProfilePhoto]:
    uid = int(user_id)
    return (
        db.query(ProfilePhoto)
        .filter(ProfilePhoto.user_id == uid)
        .order_by(ProfilePhoto.sort_order.asc(), ProfilePhoto.id.asc())
        .all()
    )


def replace_rows_from_csv(db: Session, profile: Profile) -> None:
    """Replace gallery rows so they match profile.photo_urls (used after PATCH photo_urls)."""
    uid = int(profile.user_id)
    db.query(ProfilePhoto).filter(ProfilePhoto.user_id == uid).delete(synchronize_session=False)
    parts = [p.strip() for p in (profile.photo_urls or "").split(",") if p.strip()]
    now = datetime.now(UTC)
    for i, u in enumerate(parts):
        db.add(ProfilePhoto(user_id=uid, url=u, sort_order=i, created_at=now))


def ensure_rows_from_profile_csv(db: Session, profile: Profile) -> list[ProfilePhoto]:
    rows = ordered_rows(db, profile.user_id)
    if rows:
        return rows
    parts = [p.strip() for p in (profile.photo_urls or "").split(",") if p.strip()]
    if not parts:
        return []
    now = datetime.now(UTC)
    for i, u in enumerate(parts):
        db.add(ProfilePhoto(user_id=profile.user_id, url=u, sort_order=i, created_at=now))
    db.commit()
    return ordered_rows(db, profile.user_id)


def rebuild_profile_photo_urls(profile: Profile, rows: list[ProfilePhoto]) -> None:
    profile.photo_urls = csv_from_ordered_rows(rows)


def assert_not_demo_editor(profile: Profile) -> None:
    if getattr(profile, "is_demo_profile", False):
        raise HTTPException(status_code=403, detail=api_error("profile.demo_gallery_readonly"))


def append_uploaded_photo_url(db: Session, profile: Profile, public_url: str) -> ProfilePhoto:
    assert_not_demo_editor(profile)
    url = (public_url or "").strip()
    if not url:
        raise HTTPException(status_code=400, detail=api_error("upload.empty"))
    rows = ensure_rows_from_profile_csv(db, profile)
    for r in rows:
        if (r.url or "").strip() == url:
            return r
    if len(rows) >= MAX_PHOTOS:
        raise HTTPException(status_code=400, detail=api_error("profile.photos.max_reached", max=MAX_PHOTOS))
    now = datetime.now(UTC)
    row = ProfilePhoto(user_id=profile.user_id, url=url, sort_order=len(rows), created_at=now)
    db.add(row)
    db.flush()
    merged = ordered_rows(db, profile.user_id)
    rebuild_profile_photo_urls(profile, merged)
    db.add(profile)
    db.commit()
    db.refresh(row)
    return row


def delete_photo(db: Session, profile: Profile, photo_id: int) -> None:
    assert_not_demo_editor(profile)
    uid = int(profile.user_id)
    row = db.query(ProfilePhoto).filter(ProfilePhoto.user_id == uid, ProfilePhoto.id == int(photo_id)).first()
    if row is None:
        raise HTTPException(status_code=404, detail=api_error("profile.photo.not_found"))
    prov = get_storage_provider()
    u = (row.url or "").strip()
    if u and "/demo-profiles/" not in u:
        try:
            prov.delete(u)
        except Exception:
            log.warning("profile_photo_delete_remote_failed uid=%s id=%s", uid, photo_id, exc_info=True)
    db.delete(row)
    db.flush()
    remaining = ordered_rows(db, uid)
    for i, r in enumerate(remaining):
        if r.sort_order != i:
            r.sort_order = i
    rebuild_profile_photo_urls(profile, remaining)
    db.add(profile)
    db.commit()


def set_primary_photo(db: Session, profile: Profile, photo_id: int) -> list[ProfilePhoto]:
    assert_not_demo_editor(profile)
    rows = ensure_rows_from_profile_csv(db, profile)
    idx = next((i for i, r in enumerate(rows) if r.id == int(photo_id)), None)
    if idx is None:
        raise HTTPException(status_code=404, detail=api_error("profile.photo.not_found"))
    chosen = rows.pop(idx)
    rows.insert(0, chosen)
    for i, r in enumerate(rows):
        r.sort_order = i
    rebuild_profile_photo_urls(profile, rows)
    db.add(profile)
    db.commit()
    return ordered_rows(db, profile.user_id)


def rows_to_public_payload(rows: list[ProfilePhoto]) -> list[dict]:
    items: list[dict] = []
    for i, r in enumerate(rows):
        items.append({"id": r.id, "url": r.url, "is_primary": i == 0})
    return items


def refresh_visual_embedding_best_effort(profile: Profile) -> None:
    parts = [p.strip() for p in (profile.photo_urls or "").split(",") if p.strip()]
    primary = normalize_photo_url(parts[0], demo_profile_gender=getattr(profile, "gender", None)) if parts else ""
    try:
        emb = compute_visual_embedding_from_url(primary) if primary else None
        profile.visual_embedding = emb.serialize() if emb else ""
    except Exception:
        profile.visual_embedding = getattr(profile, "visual_embedding", "") or ""
