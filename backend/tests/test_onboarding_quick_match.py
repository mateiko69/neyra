from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.deps import get_current_user, get_db
from app.api.v1.endpoints.onboarding import router as onboarding_router
from app.db.base import Base
from app.models.match import Match
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


def _client(db: Session, current_user: User) -> TestClient:
    app = FastAPI()
    app.include_router(onboarding_router, prefix="/api/v1/onboarding")

    def _override_db():
        yield db

    def _override_user():
        return current_user

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_user] = _override_user
    return TestClient(app)


def test_quick_match_reuses_newest_when_user_already_has_match():
    db = _memory_db()
    try:
        u1 = User(email="u1@example.com", hashed_password="x", is_active=True)
        u2 = User(email="u2@example.com", hashed_password="x", is_active=True)
        db.add_all([u1, u2])
        db.flush()
        db.add(
            Profile(
                user_id=int(u1.id),
                display_name="One",
                gender="woman",
                photo_urls="https://example.com/1.jpg",
                city="Kyiv",
                bio="hello there",
            )
        )
        db.add(
            Profile(
                user_id=int(u2.id),
                display_name="Two",
                gender="man",
                photo_urls="https://example.com/2.jpg",
                city="Kyiv",
                bio="hi",
            )
        )
        a, b = sorted([int(u1.id), int(u2.id)])
        db.add(Match(user_a_id=a, user_b_id=b))
        db.commit()

        c = _client(db, u1)
        r = c.post("/api/v1/onboarding/quick-match")
        assert r.status_code == 200
        body = r.json()
        assert body.get("partner_user_id") == int(u2.id)
        assert body.get("partner_name") == "Two"
        assert db.query(Match).filter(Match.user_a_id == a, Match.user_b_id == b).count() == 1
    finally:
        db.close()


def test_quick_match_zero_matches_picks_real_candidate_with_photo():
    db = _memory_db()
    try:
        viewer = User(email="v@example.com", hashed_password="x", is_active=True)
        cand_a = User(email="a@example.com", hashed_password="x", is_active=True)
        cand_b = User(email="b@example.com", hashed_password="x", is_active=True)
        db.add_all([viewer, cand_a, cand_b])
        db.flush()
        db.add(
            Profile(
                user_id=int(viewer.id),
                display_name="Viewer",
                gender="woman",
                photo_urls="v.jpg",
                city="Berlin",
                bio="viewer bio here",
                interests="music, travel",
            )
        )
        db.add(
            Profile(
                user_id=int(cand_a.id),
                display_name="Alex",
                gender="man",
                photo_urls="a.jpg",
                city="Berlin",
                bio="short",
                interests="gaming",
            )
        )
        db.add(
            Profile(
                user_id=int(cand_b.id),
                display_name="Blake",
                gender="man",
                photo_urls="b.jpg",
                city="Berlin",
                bio="also here with more overlap music travel and longer bio text",
                interests="music, travel, cooking",
            )
        )
        db.commit()

        c = _client(db, viewer)
        r = c.post("/api/v1/onboarding/quick-match")
        assert r.status_code == 200
        partner_id = int(r.json().get("partner_user_id") or 0)
        assert partner_id in {int(cand_a.id), int(cand_b.id)}
        assert db.query(Match).count() == 1
    finally:
        db.close()


def test_quick_match_demo_fallback_when_no_real_pool():
    db = _memory_db()
    try:
        viewer = User(email="v@example.com", hashed_password="x", is_active=True)
        demo_u = User(email="demo+x@neyra.local", hashed_password="x", is_active=True, is_demo=True)
        db.add_all([viewer, demo_u])
        db.flush()
        db.add(
            Profile(
                user_id=int(viewer.id),
                display_name="Viewer",
                gender="woman",
                photo_urls="v.jpg",
                city="X",
                bio="bio",
            )
        )
        db.add(
            Profile(
                user_id=int(demo_u.id),
                display_name="Demo Riley",
                gender="man",
                photo_urls="d.jpg",
                is_demo_profile=True,
                city="X",
                bio="demo",
            )
        )
        db.commit()

        c = _client(db, viewer)
        r = c.post("/api/v1/onboarding/quick-match")
        assert r.status_code == 200
        assert int(r.json().get("partner_user_id") or 0) == int(demo_u.id)
        assert db.query(Match).count() == 1
    finally:
        db.close()
