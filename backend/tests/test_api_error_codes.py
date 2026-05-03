"""API user-facing errors use stable detail.code for localization."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.deps import get_current_user, get_db
from app.api.v1.endpoints import auth, profiles, safety, subscriptions, uploads
from app.core.security import get_password_hash
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


def _detail_code(res) -> str | None:
    body = res.json()
    d = body.get("detail")
    if isinstance(d, dict):
        c = d.get("code")
        return str(c) if c else None
    return None


def test_login_and_register_error_codes():
    db = _memory_session()
    try:
        app = FastAPI()
        app.include_router(auth.router, prefix="/api/v1/auth")

        def _db():
            yield db

        app.dependency_overrides[get_db] = _db

        client = TestClient(app)
        r = client.post("/api/v1/auth/login", json={"email": "nobody@example.com", "password": "x"})
        assert r.status_code == 401
        assert _detail_code(r) == "auth.invalid_credentials"

        db.add(User(email="a@b.com", hashed_password=get_password_hash("secret"), is_active=True))
        db.commit()
        r2 = client.post("/api/v1/auth/login", json={"email": "a@b.com", "password": "wrong"})
        assert r2.status_code == 401
        assert _detail_code(r2) == "auth.invalid_credentials"

        r3 = client.post(
            "/api/v1/auth/register",
            json={"email": "a@b.com", "password": "secret234", "display_name": "X"},
        )
        assert r3.status_code == 400
        assert _detail_code(r3) == "auth.email_taken"
    finally:
        db.close()


def test_profile_patch_no_fields_code():
    db = _memory_session()
    try:
        user = User(email="u@b.com", hashed_password="x", is_active=True)
        db.add(user)
        db.flush()
        db.add(Profile(user_id=int(user.id), display_name="U"))
        db.commit()

        app = FastAPI()
        app.include_router(profiles.router, prefix="/api/v1/profiles")

        def _db():
            yield db

        def _user():
            return user

        app.dependency_overrides[get_db] = _db
        app.dependency_overrides[get_current_user] = _user

        client = TestClient(app)
        r = client.patch("/api/v1/profiles/me", json={})
        assert r.status_code == 400
        assert _detail_code(r) == "profile.no_fields_to_update"
    finally:
        db.close()


def test_upload_empty_photo_code():
    db = _memory_session()
    try:
        user = User(email="u2@b.com", hashed_password="x", is_active=True)
        db.add(user)
        db.commit()

        app = FastAPI()
        app.include_router(uploads.router, prefix="/api/v1/uploads")

        def _db():
            yield db

        def _user():
            return user

        app.dependency_overrides[get_db] = _db
        app.dependency_overrides[get_current_user] = _user

        client = TestClient(app)
        r = client.post(
            "/api/v1/uploads/photo",
            files={"file": ("empty.jpg", b"", "image/jpeg")},
        )
        assert r.status_code == 400
        assert _detail_code(r) == "upload.empty"
    finally:
        db.close()


def test_subscription_invalid_plan_code():
    db = _memory_session()
    try:
        user = User(email="u3@b.com", hashed_password="x", is_active=True)
        db.add(user)
        db.commit()

        app = FastAPI()
        app.include_router(subscriptions.router, prefix="/api/v1/subscriptions")

        def _db():
            yield db

        def _user():
            return user

        app.dependency_overrides[get_db] = _db
        app.dependency_overrides[get_current_user] = _user

        client = TestClient(app)
        r = client.post("/api/v1/subscriptions/checkout", json={"plan_code": "enterprise"})
        assert r.status_code == 400
        assert _detail_code(r) == "subscription.invalid_plan"
    finally:
        db.close()


def test_safety_report_reason_required_code():
    db = _memory_session()
    try:
        a = User(email="a4@b.com", hashed_password="x", is_active=True)
        b = User(email="b4@b.com", hashed_password="x", is_active=True)
        db.add(a)
        db.add(b)
        db.commit()

        app = FastAPI()
        app.include_router(safety.router, prefix="/api/v1/users")

        def _db():
            yield db

        def _user():
            return a

        app.dependency_overrides[get_db] = _db
        app.dependency_overrides[get_current_user] = _user

        client = TestClient(app)
        r = client.post(f"/api/v1/users/{b.id}/report", json={"reason": ""})
        assert r.status_code == 400
        assert _detail_code(r) == "safety.report_reason_required"
    finally:
        db.close()
