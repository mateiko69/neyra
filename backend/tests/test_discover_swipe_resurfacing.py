from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.deps import get_current_user, get_db
from app.api.v1.endpoints.discover import PASS_COOLDOWN_HOURS, router as discover_router
from app.db.base import Base
from app.models.profile import Profile
from app.models.swipe import Swipe
from app.models.user import User
from app.services.demo_mode import set_demo_mode_enabled
from app.api.v1.endpoints.swipes import router as swipes_router


def _memory_engine():
    engine = create_engine(
        "sqlite://",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return engine


def _client(engine, current_user: User) -> TestClient:
    app = FastAPI()
    app.include_router(discover_router, prefix="/api/v1/discover")
    app.include_router(swipes_router, prefix="/api/v1/swipes")
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)

    def _override_db():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    def _override_user():
        return current_user

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_user] = _override_user
    return TestClient(app)


def test_discover_passed_profiles_are_soft_ranked_not_hard_excluded():
    engine = _memory_engine()
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    db = SessionLocal()
    try:
        viewer = User(email="viewer@ex.com", hashed_password="x", is_active=True, is_demo=False)
        cand = User(email="cand@ex.com", hashed_password="x", is_active=True, is_demo=False)
        db.add_all([viewer, cand])
        db.flush()
        set_demo_mode_enabled(db, False)

        db.add(
            Profile(
                user_id=int(viewer.id),
                display_name="Viewer",
                gender="woman",
                interested_in="men",
                min_preferred_age=18,
                max_preferred_age=80,
                photo_urls="v.jpg",
                age=26,
                onboarding_completed=True,
            )
        )
        db.add(
            Profile(
                user_id=int(cand.id),
                display_name="Cand",
                gender="man",
                interested_in="women",
                photo_urls="c.jpg",
                age=28,
                onboarding_completed=True,
            )
        )
        db.commit()

        c = _client(engine, viewer)

        # Initially visible.
        r0 = c.get("/api/v1/discover/feed?limit=10")
        assert r0.status_code == 200
        ids0 = [int(x.get("user_id") or 0) for x in (r0.json() or []) if isinstance(x, dict)]
        assert int(cand.id) in ids0

        # Pass now -> candidate should still be in feed (soft-ranked, not hard-excluded).
        r_sw = c.post("/api/v1/swipes", json={"target_user_id": int(cand.id), "liked": False})
        assert r_sw.status_code == 200

        r1 = c.get("/api/v1/discover/feed?limit=10")
        assert r1.status_code == 200
        ids1 = [int(x.get("user_id") or 0) for x in (r1.json() or []) if isinstance(x, dict)]
        assert int(cand.id) in ids1

        # Make pass old -> candidate still appears.
        s = (
            db.query(Swipe)
            .filter(Swipe.swiper_id == int(viewer.id), Swipe.target_user_id == int(cand.id))
            .order_by(Swipe.id.desc())
            .first()
        )
        assert s is not None
        s.created_at = datetime.now(UTC) - timedelta(hours=PASS_COOLDOWN_HOURS + 1)
        db.add(s)
        db.commit()

        r2 = c.get("/api/v1/discover/feed?limit=10")
        assert r2.status_code == 200
        ids2 = [int(x.get("user_id") or 0) for x in (r2.json() or []) if isinstance(x, dict)]
        assert int(cand.id) in ids2
    finally:
        db.close()

