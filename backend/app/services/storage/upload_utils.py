"""Shared image upload validation and persistence helpers."""

from __future__ import annotations

import logging
import uuid
from pathlib import Path

from fastapi import HTTPException, UploadFile

from app.api.api_errors import api_error
from app.services.storage.service import get_storage_provider

log = logging.getLogger(__name__)

MAX_IMAGE_BYTES = 8 * 1024 * 1024  # 8 MB
MAX_AUDIO_BYTES = 3 * 1024 * 1024  # ~3 MB (short voice notes)
ALLOWED_IMAGE_TYPES = frozenset(
    {
        "image/jpeg",
        "image/png",
        "image/webp",
        "image/gif",
    }
)
ALLOWED_AUDIO_TYPES = frozenset(
    {
        "audio/webm",
        "audio/mp4",
        "audio/aac",
        "audio/m4a",
        "audio/x-m4a",
    }
)

_CT_TO_EXT = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "image/gif": "gif",
}

_EXT_FROM_NAME = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".webm": "audio/webm",
    ".m4a": "audio/mp4",
    ".mp4": "audio/mp4",
    ".aac": "audio/aac",
}


def _sniff_image_mime(content: bytes) -> str | None:
    if len(content) >= 3 and content[0:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if len(content) >= 8 and content[0:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if len(content) >= 6 and content[0:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if len(content) >= 12 and content[0:4] == b"RIFF" and content[8:12] == b"WEBP":
        return "image/webp"
    return None


def _mime_from_filename(filename: str | None) -> str | None:
    if not filename:
        return None
    suf = Path(filename).suffix.lower()
    return _EXT_FROM_NAME.get(suf)


async def read_validate_image(file: UploadFile) -> tuple[bytes, str]:
    content = await file.read()
    if not content:
        log.warning("read_validate_image rejected: empty file filename=%s", file.filename)
        raise HTTPException(status_code=400, detail=api_error("upload.empty"))
    if len(content) > MAX_IMAGE_BYTES:
        log.warning(
            "read_validate_image rejected: too large bytes=%s max=%s filename=%s",
            len(content),
            MAX_IMAGE_BYTES,
            file.filename,
        )
        raise HTTPException(status_code=400, detail=api_error("upload.image_too_large"))
    ct = (file.content_type or "").split(";")[0].strip().lower()
    if ct in ("", "application/octet-stream", "binary/octet-stream"):
        ct = ""
    if ct not in ALLOWED_IMAGE_TYPES:
        sniffed = _sniff_image_mime(content)
        if sniffed:
            ct = sniffed
        else:
            from_name = _mime_from_filename(file.filename)
            if from_name:
                ct = from_name
    if ct not in ALLOWED_IMAGE_TYPES:
        log.warning(
            "read_validate_image rejected: disallowed content_type=%s filename=%s",
            file.content_type,
            file.filename,
        )
        raise HTTPException(status_code=400, detail=api_error("upload.image_type_not_allowed"))
    ext = _CT_TO_EXT.get(ct)
    if not ext:
        log.warning("read_validate_image rejected: no ext for ct=%s filename=%s", ct, file.filename)
        raise HTTPException(status_code=400, detail=api_error("upload.image_type_not_allowed"))
    return content, ext


def persist_profile_gallery_image(user_id: int, ext: str, content: bytes) -> str:
    """Persist to object storage/local under ``users/<id>/photos/<uuid>.<ext>``."""
    filename = f"users/{int(user_id)}/photos/{uuid.uuid4().hex}.{ext}"
    provider = get_storage_provider()
    url = provider.save(filename, content)
    log.info(
        "stored upload user_id=%s bytes=%s filename=%s public_url=%s",
        user_id,
        len(content),
        filename,
        url,
    )
    return url


def persist_user_image(user_id: int, ext: str, content: bytes) -> str:
    return persist_profile_gallery_image(user_id, ext, content)


def persist_verification_selfie(user_id: int, ext: str, content: bytes) -> str:
    """Persist verification frames; returns public URL or \"\" if storage is unavailable (embedding flow still runs)."""
    filename = f"verification/{user_id}_{uuid.uuid4().hex}.{ext}"
    try:
        provider = get_storage_provider()
        url = provider.save(filename, content)
        log.info(
            "stored verification selfie user_id=%s bytes=%s filename=%s public_url=%s",
            user_id,
            len(content),
            filename,
            url,
        )
        return url
    except Exception:
        log.warning("persist_verification_selfie failed user_id=%s", user_id, exc_info=True)
        return ""


def _audio_ext_for_mime(mime: str) -> str:
    if mime == "audio/webm":
        return "webm"
    # iOS-friendly container (AAC usually inside mp4/m4a)
    if mime in {"audio/mp4", "audio/m4a", "audio/x-m4a"}:
        return "m4a"
    if mime == "audio/aac":
        return "aac"
    return "bin"


async def read_validate_audio(file: UploadFile) -> tuple[bytes, str]:
    content = await file.read()
    if not content:
        log.warning("read_validate_audio rejected: empty file filename=%s", file.filename)
        raise HTTPException(status_code=400, detail=api_error("upload.empty"))
    if len(content) > MAX_AUDIO_BYTES:
        log.warning(
            "read_validate_audio rejected: too large bytes=%s max=%s filename=%s",
            len(content),
            MAX_AUDIO_BYTES,
            file.filename,
        )
        raise HTTPException(status_code=400, detail=api_error("upload.audio_too_large"))
    ct = (file.content_type or "").split(";")[0].strip().lower()
    if ct in ("", "application/octet-stream", "binary/octet-stream"):
        ct = ""
    if ct not in ALLOWED_AUDIO_TYPES:
        from_name = _mime_from_filename(file.filename)
        if from_name:
            ct = from_name
    if ct not in ALLOWED_AUDIO_TYPES:
        log.warning(
            "read_validate_audio rejected: disallowed content_type=%s filename=%s",
            file.content_type,
            file.filename,
        )
        raise HTTPException(status_code=400, detail=api_error("upload.audio_type_not_allowed"))
    return content, ct


def persist_user_voice_note(user_id: int, content_type: str, content: bytes) -> str:
    ext = _audio_ext_for_mime(content_type)
    filename = f"voice_{user_id}_{uuid.uuid4().hex}.{ext}"
    provider = get_storage_provider()
    url = provider.save(filename, content)
    log.info(
        "stored voice_note user_id=%s bytes=%s filename=%s content_type=%s public_url=%s",
        user_id,
        len(content),
        filename,
        content_type,
        url,
    )
    return url
