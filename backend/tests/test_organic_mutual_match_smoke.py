"""E2E-style smoke: two real users discover each other, mutual like, match, lists + nav, idempotent second like, dev reset."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.api.deps import get_current_user, get_db
from app.api.v1.endpoints import dev, discover, matches, messages, nav, swipes
from app.core.config import settings
from app.db.base import Base
from app.models.match import Match
from app.models.profile import Profile
from app.models.user import User
from app.services.demo_mode import set_demo_mode_enabled


def _memory_db() -> Session:
    engine = create_engine(
        "sqlite://",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return Session(engine)


def _build_app(db: Session):
    app = FastAPI()
    p = "/api/v1"
    app.include_router(discover.router, prefix=f"{p}/discover", tags=["discover"])
    app.include_router(swipes.router, prefix=f"{p}/swipes", tags=["swipes"])
    app.include_router(matches.router, prefix=f"{p}/matches", tags=["matches"])
    app.include_router(messages.router, prefix=f"{p}/messages", tags=["messages"])
    app.include_router(nav.router, prefix=f"{p}/nav", tags=["nav"])
    app.include_router(dev.router, prefix=f"{p}/dev", tags=["dev"])

    def _db():
        yield db

    app.dependency_overrides[get_db] = _db
    return app


def test_organic_mutual_match_full_loop_and_reset(monkeypatch):
    monkeypatch.setattr(settings, "DEV_TOOLS_ENABLED", True)
    db = _memory_db()
    try:
        set_demo_mode_enabled(db, False)
        user_a = User(email="organic-smoke-a@example.com", hashed_password="x", is_active=True, is_demo=False)
        user_b = User(email="organic-smoke-b@example.com", hashed_password="x", is_active=True, is_demo=False)
        db.add_all([user_a, user_b])
        db.flush()
        db.add(
            Profile(
                user_id=int(user_a.id),
                display_name="Smoke A",
                gender="man",
                interested_in="women",
                age=29,
                min_preferred_age=18,
                max_preferred_age=80,
                photo_urls="a.jpg",
                city="Berlin",
                bio="x" * 40,
                interests="travel,gym,music",
                onboarding_completed=True,
            )
        )
        db.add(
            Profile(
                user_id=int(user_b.id),
                display_name="Smoke B",
                gender="woman",
                interested_in="men",
                age=28,
                min_preferred_age=18,
                max_preferred_age=80,
                photo_urls="b.jpg",
                city="Munich",
                bio="y" * 40,
                interests="coffee,hiking,books",
                onboarding_completed=True,
            )
        )
        db.commit()

        holder: dict[str, User] = {"current": user_a}
        app = _build_app(db)

        def _user():
            return holder["current"]

        app.dependency_overrides[get_current_user] = _user
        client = TestClient(app)

        def feed_ids() -> list[int]:
            r = client.get("/api/v1/discover/feed?limit=20&offset=0")
            assert r.status_code == 200
            return [int(x.get("user_id") or 0) for x in (r.json() or []) if isinstance(x, dict)]

        holder["current"] = user_a
        assert int(user_b.id) in feed_ids()
        nav0 = client.get("/api/v1/nav/badges").json() or {}
        assert int(nav0.get("matches") or 0) == 0

        holder["current"] = user_b
        assert int(user_a.id) in feed_ids()

        holder["current"] = user_a
        # Swipes API uses liked (bool), not action=like.
        r1 = client.post("/api/v1/swipes", json={"target_user_id": int(user_b.id), "liked": True})
        assert r1.status_code == 200
        body1 = r1.json() or {}
        assert body1.get("matched") is not True

        holder["current"] = user_b
        r2 = client.post("/api/v1/swipes", json={"target_user_id": int(user_a.id), "liked": True})
        assert r2.status_code == 200
        body2 = r2.json() or {}
        assert body2.get("matched") is True

        match_count = int(db.query(Match).count())
        assert match_count == 1

        holder["current"] = user_a
        mrows = client.get("/api/v1/matches")
        assert mrows.status_code == 200
        partners_a = [int(x.get("partner_user_id") or 0) for x in (mrows.json() or []) if isinstance(x, dict)]
        assert int(user_b.id) in partners_a

        conv_a = client.get("/api/v1/messages/conversations")
        assert conv_a.status_code == 200
        conv_partners_a = [int(x.get("partner_user_id") or 0) for x in (conv_a.json() or []) if isinstance(x, dict)]
        assert int(user_b.id) in conv_partners_a

        nav_a = client.get("/api/v1/nav/badges")
        assert nav_a.status_code == 200
        na = nav_a.json() or {}
        assert int(na.get("matches") or 0) == 1
        assert int(na.get("new_matches") or 0) >= 1

        holder["current"] = user_b
        r_dup = client.post("/api/v1/swipes", json={"target_user_id": int(user_a.id), "liked": True})
        assert r_dup.status_code == 200
        assert int(db.query(Match).count()) == 1

        holder["current"] = user_a
        rr = client.post("/api/v1/dev/reset-dating-state")
        assert rr.status_code == 200
        assert int(rr.json().get("swipes_deleted") or 0) >= 1
        assert int(rr.json().get("matches_deleted") or 0) >= 1

        nav_after = client.get("/api/v1/nav/badges").json() or {}
        assert int(nav_after.get("matches") or 0) == 0

        ids_after = feed_ids()
        assert int(user_b.id) in ids_after
        holder["current"] = user_b
        assert int(user_a.id) in feed_ids()
    finally:
        db.close()
