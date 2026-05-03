"""Profile and chat media under /uploads/... are readable without authentication."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app

_MIN_JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00\xff\xdb"


def _public_prefix() -> str:
    prefix = (getattr(settings, "UPLOAD_PUBLIC_PREFIX", None) or "/uploads").strip()
    return prefix if prefix.startswith("/") else f"/{prefix}"


def test_public_upload_get_200_without_auth(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))
    rel = "777_public_read_test.jpg"
    (tmp_path / rel).write_bytes(_MIN_JPEG)

    client = TestClient(app)
    r = client.get(f"{_public_prefix()}/{rel}")
    assert r.status_code == 200, r.text
    assert r.content.startswith(b"\xff\xd8")


def test_public_upload_rejects_traversal() -> None:
    client = TestClient(app)
    r = client.get(f"{_public_prefix()}/../.env")
    assert r.status_code == 404


def test_public_upload_rejects_disallowed_extension() -> None:
    client = TestClient(app)
    r = client.get(f"{_public_prefix()}/secret.exe")
    assert r.status_code == 404
