from __future__ import annotations

from app.core.config import settings
from app.services.storage.service import s3_fully_configured


def test_s3_alias_env_names_enable_storage(monkeypatch):
    monkeypatch.setattr(settings, "S3_BUCKET", "demo-bucket")
    monkeypatch.setattr(settings, "S3_PUBLIC_BASE_URL", "https://cdn.example.com")
    monkeypatch.setattr(settings, "S3_ACCESS_KEY_ID", "")
    monkeypatch.setattr(settings, "S3_SECRET_ACCESS_KEY", "")
    monkeypatch.setattr(settings, "AWS_ACCESS_KEY_ID", "alias-key")
    monkeypatch.setattr(settings, "AWS_SECRET_ACCESS_KEY", "alias-secret")
    assert s3_fully_configured() is True

