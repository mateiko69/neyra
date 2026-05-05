"""Resolve storage backend: local (dev), S3/R2 (durable), or unavailable (prod misconfigured)."""

from __future__ import annotations

import logging

from app.core.config import settings
from app.services.storage.local_provider import LocalStorageProvider
from app.services.storage.s3_provider import S3StorageProvider
from app.services.storage.unavailable_provider import UnavailableStorageProvider

log = logging.getLogger(__name__)


def _is_production_env() -> bool:
    return (settings.ENV or "").strip().lower() in ("production", "prod")


def s3_fully_configured() -> bool:
    """True when required vars for durable public URLs are present (R2 or AWS S3)."""
    if not (settings.S3_BUCKET or "").strip():
        return False
    if not (settings.S3_ACCESS_KEY_ID or "").strip():
        return False
    if not (settings.S3_SECRET_ACCESS_KEY or "").strip():
        return False
    if not (getattr(settings, "S3_PUBLIC_BASE_URL", None) or "").strip():
        return False
    return True


def get_storage_provider():
    """
    Production (ENV=production|prod):
      - Use S3/R2 when S3_BUCKET, credentials, and S3_PUBLIC_BASE_URL are set.
      - Never use local container disk for uploads (ephemeral on Railway).
      - If S3 is incomplete, use UnavailableStorageProvider (save returns \"\").

    Development:
      - STORAGE_PROVIDER=s3 with full S3 env → S3.
      - Else → local filesystem.
    """
    if _is_production_env():
        if s3_fully_configured():
            log.info("storage_provider=s3 env=production")
            return S3StorageProvider()
        log.warning(
            "production_storage_requires_s3_r2: Railway disk is ephemeral. "
            "Set S3_BUCKET, S3_ACCESS_KEY_ID, S3_SECRET_ACCESS_KEY, S3_PUBLIC_BASE_URL "
            "and for Cloudflare R2 also S3_ENDPOINT_URL (and usually S3_REGION=auto). "
            "Upload endpoints will return 503 until configured."
        )
        return UnavailableStorageProvider()

    want_s3 = (settings.STORAGE_PROVIDER or "").strip().lower() == "s3"
    if want_s3 and s3_fully_configured():
        log.info("storage_provider=s3 env=development")
        return S3StorageProvider()
    if want_s3 and not s3_fully_configured():
        log.warning(
            "STORAGE_PROVIDER=s3 but S3_* env incomplete; using local filesystem for development"
        )
    return LocalStorageProvider()
