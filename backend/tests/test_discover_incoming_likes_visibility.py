from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.deps import get_current_user, get_db
from app.api.v1.endpoints.discover import router as discover_router
from app.api.v1.endpoints.likes import router as likes_router
from app.api.v1.endpoints.matches import router as matches_router
from app.core.config import settings
from app.api.v1.endpoints.swipes import router as swipes_router
from app.db.base import Base
from app.models.profile import Profile
from app.models.user import User


def _memory_db() -> Session:
    engine = create_engine(
        "sqlite://",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return Session(engine)


def _build_app(db: Session, holder: dict[str, User]) -> TestClient:
    app = FastAPI()
    app.include_router(discover_router, prefix="/api/v1/discover")
    app.include_router(swipes_router, prefix="/api/v1/swipes")
    app.include_router(likes_router, prefix="/api/v1/likes")
    app.include_router(matches_router, prefix="/api/v1/matches")

    def _override_db():
        yield db

    def _override_user():
        return holder["current"]

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_user] = _override_user
    return TestClient(app)


def _seed_pair(db: Session) -> tuple[User, User]:
    a = User(email="incoming-visible-a@example.com", hashed_password="x", is_active=True)
    b = User(email="incoming-visible-b@example.com", hashed_password="x", is_active=True)
    db.add_all([a, b])
    db.flush()
    db.add(
        Profile(
            user_id=int(a.id),
            display_name="A",
            gender="man",
            interested_in="women",
            age=28,
            min_preferred_age=18,
            max_preferred_age=80,
            photo_urls="a.jpg",
            onboarding_completed=True,
        )
    )
    db.add(
        Profile(
            user_id=int(b.id),
            display_name="B",
            gender="woman",
            interested_in="men",
            age=27,
            min_preferred_age=18,
            max_preferred_age=80,
            photo_urls="b.jpg",
            onboarding_completed=True,
        )
    )
    db.commit()
    return a, b


def _feed_ids(client: TestClient) -> list[int]:
    r = client.get("/api/v1/discover/feed?limit=20&offset=0")
    assert r.status_code == 200
    return [int(x.get("user_id") or 0) for x in (r.json() or []) if isinstance(x, dict)]


def _incoming_ids(client: TestClient) -> list[int]:
    r = client.get("/api/v1/likes/incoming?limit=20")
    assert r.status_code == 200
    items = (r.json() or {}).get("items") or []
    return [int(x.get("user_id") or 0) for x in items if isinstance(x, dict)]


def test_incoming_like_stays_discoverable_until_mutual_match():
    db = _memory_db()
    try:
        a, b = _seed_pair(db)
        holder: dict[str, User] = {"current": a}
        client = _build_app(db, holder)

        holder["current"] = a
        r_like = client.post("/api/v1/swipes", json={"target_user_id": int(b.id), "liked": True})
        assert r_like.status_code == 200
        assert r_like.json().get("matched") is False

        # Free user path: B sees A in Discover despite incoming like teaser.
        holder["current"] = b
        assert int(a.id) in _feed_ids(client)
        assert int(a.id) in _incoming_ids(client)

        r_back = client.post("/api/v1/swipes", json={"target_user_id": int(a.id), "liked": True})
        assert r_back.status_code == 200
        assert r_back.json().get("matched") is True
        assert r_back.json().get("liked") is True

        # After match: candidate leaves Discover + incoming likes, appears in Matches.
        assert int(a.id) not in _feed_ids(client)
        assert int(a.id) not in _incoming_ids(client)
        r_matches = client.get("/api/v1/matches")
        assert r_matches.status_code == 200
        assert any(int(x.get("partner_user_id") or 0) == int(a.id) for x in (r_matches.json() or []))
    finally:
        db.close()


def test_paid_reveal_still_allows_match_and_pass_penalizes_discover(monkeypatch):
    db = _memory_db()
    try:
        monkeypatch.setattr(settings, "DEV_TOOLS_ENABLED", True)
        a, b = _seed_pair(db)
        holder: dict[str, User] = {"current": a}
        client = _build_app(db, holder)

        # A likes B first so B has incoming like teaser.
        holder["current"] = a
        client.post("/api/v1/swipes", json={"target_user_id": int(b.id), "liked": True})

        # Premium reveal path (monkeypatch inside endpoint module).
        import app.api.v1.endpoints.likes as likes_mod

        monkeypatch.setattr(likes_mod, "_premium_flags", lambda _db, _u: (True, False))
        holder["current"] = b
        r_reveal = client.post("/api/v1/likes/reveal", json={"user_id": int(a.id)})
        assert r_reveal.status_code == 200
        assert r_reveal.json().get("ok") is True

        # Matching from Likes remains possible for premium users.
        r_like_back = client.post("/api/v1/likes/respond", json={"user_id": int(a.id), "action": "like"})
        assert r_like_back.status_code == 200
        assert r_like_back.json().get("matched") is True

        # Explicit pass/dislike applies ranking penalty in Discover.
        c = User(email="incoming-visible-c@example.com", hashed_password="x", is_active=True)
        db.add(c)
        db.flush()
        db.add(
            Profile(
                user_id=int(c.id),
                display_name="C",
                gender="man",
                interested_in="women",
                age=29,
                min_preferred_age=18,
                max_preferred_age=80,
                photo_urls="c.jpg",
                onboarding_completed=True,
            )
        )
        db.commit()
        assert int(c.id) in _feed_ids(client)
        r_pass = client.post("/api/v1/swipes", json={"target_user_id": int(c.id), "liked": False})
        assert r_pass.status_code == 200
        r_dbg = client.get("/api/v1/discover/feed?limit=20&offset=0&include_debug=true")
        assert r_dbg.status_code == 200
        payload = r_dbg.json() or {}
        debug = payload.get("debug") or {}
        assert int(debug.get("pass_penalty_applied") or 0) >= 1
    finally:
        db.close()
