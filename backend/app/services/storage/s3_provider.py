from urllib.parse import urlsplit

import boto3

from app.core.config import settings
from app.services.storage.base import StorageProvider

class S3StorageProvider(StorageProvider):
    def save(self, filename: str, content: bytes) -> str:
        # Minimal stub: store key reference as s3:// URL.
        # Production should upload using boto3 with settings.S3_* credentials.
        return f"s3://{settings.S3_BUCKET or 'bucket'}/{filename}"

    def delete(self, url_or_key: str) -> None:
        raw = (url_or_key or "").strip()
        if not raw:
            return
        key = ""
        bucket = settings.S3_BUCKET or ""
        if raw.startswith("s3://"):
            parts = urlsplit(raw)
            bucket = (parts.netloc or "").strip() or bucket
            key = (parts.path or "").lstrip("/")
        else:
            # Allow passing raw keys directly.
            key = raw.lstrip("/")
        if not bucket or not key:
            return
        try:
            s3 = boto3.client(
                "s3",
                region_name=settings.S3_REGION or None,
                aws_access_key_id=settings.S3_ACCESS_KEY_ID or None,
                aws_secret_access_key=settings.S3_SECRET_ACCESS_KEY or None,
            )
            s3.delete_object(Bucket=bucket, Key=key)
        except Exception:
            return
