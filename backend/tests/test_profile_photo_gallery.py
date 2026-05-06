"""Profile gallery REST: upload / delete / set primary (SQLite + mocked storage)."""

from __future__ import annotations

import io

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401 — register tables
from app.api.deps import get_current_user, get_db
from app.api.v1.endpoints import profile_photos
from app.db.base import Base
from app.models.profile import Profile
from app.models.user import User


def _memory_session() -> Session:
    engine = create_engine(
        "sqlite://",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return Session(engine)


def _tiny_png() -> bytes:
    return (
        b"\x89PNG\r\n\x1a\n"
        b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
        b"\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00"
        b"\x00\x00\x00IEND\xaeB`\x82"
    )


def _gallery_client(db: Session, user: User, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    seq = {"n": 0}

    def _fake_persist(uid: int, ext: str, content: bytes) -> str:
        seq["n"] += 1
        return f"https://cdn.example/users/{int(uid)}/photos/p{seq['n']}-{len(content)}.{ext}"

    monkeypatch.setattr(profile_photos, "uploads_are_available", lambda: True)
    monkeypatch.setattr(profile_photos, "persist_user_image", _fake_persist)
    monkeypatch.setattr(profile_photos, "refresh_visual_embedding_best_effort", lambda p: None)
    monkeypatch.setattr(profile_photos, "bump_user_cache_version", lambda *a, **k: None)

    app = FastAPI()
    app.include_router(profile_photos.router, prefix="/api/v1/profile")

    def _db():
        yield db

    def _user():
        return user

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_current_user] = _user
    return TestClient(app)


def test_profile_gallery_upload_list_primary_delete(monkeypatch: pytest.MonkeyPatch) -> None:
    db = _memory_session()
    try:
        user = User(email="gal@b.com", hashed_password="x", is_active=True)
        db.add(user)
        db.flush()
        db.add(Profile(user_id=int(user.id), display_name="G", is_demo_profile=False))
        db.commit()

        client = _gallery_client(db, user, monkeypatch)
        png = _tiny_png()

        r1 = client.post("/api/v1/profile/photos", files={"file": ("a.png", io.BytesIO(png), "image/png")})
        assert r1.status_code == 200
        b1 = r1.json()
        assert len(b1["photos"]) == 1
        assert b1["photos"][0]["is_primary"] is True
        id1 = int(b1["photos"][0]["id"])

        r2 = client.post("/api/v1/profile/photos", files={"file": ("b.png", io.BytesIO(png), "image/png")})
        assert r2.status_code == 200
        b2 = r2.json()
        assert len(b2["photos"]) == 2
        assert b2["photos"][0]["is_primary"] is True
        id2 = int(b2["photos"][1]["id"])

        r_prim = client.post(f"/api/v1/profile/photos/{id2}/primary")
        assert r_prim.status_code == 200
        bp = r_prim.json()
        assert [p["id"] for p in bp["photos"]] == [id2, id1]

        listed = client.get("/api/v1/profile/photos")
        assert listed.status_code == 200
        jl = listed.json()
        assert [x["id"] for x in jl] == [id2, id1]

        rd = client.delete(f"/api/v1/profile/photos/{id2}")
        assert rd.status_code == 200

        tail = client.get("/api/v1/profile/photos")
        assert tail.status_code == 200
        assert len(tail.json()) == 1
        assert tail.json()[0]["id"] == id1
    finally:
        db.close()


def test_profile_gallery_upload_503_when_storage_unconfigured(monkeypatch: pytest.MonkeyPatch) -> None:
    db = _memory_session()
    try:
        user = User(email="off@b.com", hashed_password="x", is_active=True)
        db.add(user)
        db.flush()
        db.add(Profile(user_id=int(user.id), display_name="O"))
        db.commit()

        monkeypatch.setattr(profile_photos, "uploads_are_available", lambda: False)
        monkeypatch.setattr(profile_photos, "refresh_visual_embedding_best_effort", lambda p: None)
        monkeypatch.setattr(profile_photos, "bump_user_cache_version", lambda *a, **k: None)

        app = FastAPI()
        app.include_router(profile_photos.router, prefix="/api/v1/profile")

        def _db():
            yield db

        def _user():
            return user

        app.dependency_overrides[get_db] = _db
        app.dependency_overrides[get_current_user] = _user

        client = TestClient(app)
        png = _tiny_png()
        r = client.post("/api/v1/profile/photos", files={"file": ("a.png", io.BytesIO(png), "image/png")})
        assert r.status_code == 503
        detail = r.json().get("detail")
        assert isinstance(detail, dict)
        assert detail.get("code") == "upload.storage_unavailable"
    finally:
        db.close()
