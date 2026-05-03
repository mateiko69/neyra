"""Demo profile images are served at /demo-profiles/... (same path as catalog photo_main_path)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.demo_mode import demo_profiles_public_dir


def test_demo_profiles_public_dir_is_named_demo_profiles() -> None:
    d = demo_profiles_public_dir()
    assert d.name == "demo-profiles"
    assert "public" in d.parts


def test_demo_profiles_main_jpg_returns_200_when_asset_present() -> None:
    """Requires frontend/public/demo-profiles/women/demo_001/main.jpg in the workspace."""
    p = demo_profiles_public_dir() / "women" / "demo_001" / "main.jpg"
    if not p.is_file():
        pytest.skip(f"missing demo photo: {p}")
    client = TestClient(app)
    r = client.get("/demo-profiles/women/demo_001/main.jpg")
    assert r.status_code == 200
    ct = (r.headers.get("content-type") or "").lower()
    assert "jpeg" in ct or "jpg" in ct or r.content[:2] == b"\xff\xd8"
