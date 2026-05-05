"""S3-compatible object storage (AWS S3, Cloudflare R2, MinIO, etc.)."""

from __future__ import annotations

import logging
import mimetypes
from pathlib import Path
from urllib.parse import urlsplit

import boto3
from botocore.config import Config

from app.core.config import settings
from app.services.storage.base import StorageProvider

log = logging.getLogger(__name__)


def _s3_client():
    kwargs: dict = {
        "service_name": "s3",
        "aws_access_key_id": (settings.S3_ACCESS_KEY_ID or "").strip() or None,
        "aws_secret_access_key": (settings.S3_SECRET_ACCESS_KEY or "").strip() or None,
        "config": Config(signature_version="s3v4"),
    }
    region = (settings.S3_REGION or "").strip()
    if region:
        kwargs["region_name"] = region
    endpoint = (getattr(settings, "S3_ENDPOINT_URL", None) or "").strip()
    if endpoint:
        kwargs["endpoint_url"] = endpoint
    return boto3.client(**kwargs)


def _public_base() -> str:
    return (getattr(settings, "S3_PUBLIC_BASE_URL", None) or "").strip().rstrip("/")


class S3StorageProvider(StorageProvider):
    def save(self, filename: str, content: bytes) -> str:
        bucket = (settings.S3_BUCKET or "").strip()
        base = _public_base()
        if not bucket or not base:
            raise RuntimeError("S3_BUCKET and S3_PUBLIC_BASE_URL are required for S3 storage")

        key = filename.lstrip("/")
        content_type = mimetypes.guess_type(key)[0]
        if not content_type:
            suf = Path(key).suffix.lower()
            if suf in (".jpg", ".jpeg"):
                content_type = "image/jpeg"
            elif suf == ".png":
                content_type = "image/png"
            elif suf == ".webp":
                content_type = "image/webp"
            elif suf == ".gif":
                content_type = "image/gif"
            elif suf == ".webm":
                content_type = "audio/webm"
            elif suf in (".m4a", ".mp4"):
                content_type = "audio/mp4"
            else:
                content_type = "application/octet-stream"

        s3 = _s3_client()
        s3.put_object(Bucket=bucket, Key=key, Body=content, ContentType=content_type)
        public_url = f"{base}/{key}"
        log.debug("s3_put_object ok bucket=%s key=%s bytes=%s", bucket, key, len(content))
        return public_url

    def delete(self, url_or_key: str) -> None:
        raw = (url_or_key or "").strip()
        if not raw:
            return
        bucket = (settings.S3_BUCKET or "").strip()
        if not bucket:
            return
        key = ""
        if raw.startswith("s3://"):
            parts = urlsplit(raw)
            key = (parts.path or "").lstrip("/")
            nb = (parts.netloc or "").strip()
            if nb:
                bucket = nb
        else:
            base = _public_base()
            if base and raw.startswith(base + "/"):
                key = raw[len(base) + 1 :].split("?", 1)[0]
            elif raw.startswith("http://") or raw.startswith("https://"):
                try:
                    u = urlsplit(raw)
                    path = (u.path or "").lstrip("/")
                    if path:
                        key = path.split("?", 1)[0]
                except Exception:
                    key = ""
            else:
                key = raw.lstrip("/")
        if not key:
            return
        try:
            s3 = _s3_client()
            s3.delete_object(Bucket=bucket, Key=key)
        except Exception:
            log.warning("s3_delete_object_failed bucket=%s key=%s", bucket, key, exc_info=True)
