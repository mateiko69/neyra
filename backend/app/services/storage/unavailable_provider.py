"""Storage provider used in production when S3/R2 is not configured.

Railway/local container disk is ephemeral; we must not persist user photos there in production.
"""

from __future__ import annotations

import logging

from app.services.storage.base import StorageProvider

log = logging.getLogger(__name__)


class UnavailableStorageProvider(StorageProvider):
    """Does not write bytes to disk or object storage; returns empty public URL."""

    def save(self, filename: str, content: bytes) -> str:
        log.warning(
            "storage_save_skipped_unavailable filename=%s bytes=%s — production requires S3/R2 (see DEPLOYMENT.md)",
            filename,
            len(content),
        )
        return ""

    def delete(self, url_or_key: str) -> None:
        return
