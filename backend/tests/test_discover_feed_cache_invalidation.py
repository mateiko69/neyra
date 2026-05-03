from datetime import UTC, datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.deps import get_current_user, get_db
from app.api.v1.endpoints.discover import router as discover_router
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


class DummyUser:
    def __init__(self, user_id: int, email: str = "u@example.com"):
        self.id = int(user_id)
        self.email = email


def _build_client(db: Session, current_user_id: int) -> TestClient:
    app = FastAPI()
    app.include_router(discover_router, prefix="/api/v1/discover")
    app.include_router(swipes_router, prefix="/api/v1/swipes")

    def _override_db():
        yield db

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_user] = lambda: DummyUser(current_user_id)
    return TestClient(app)


def _seed_user_with_profile(db: Session, user_id: int, name: str) -> None:
    db.add(User(id=int(user_id), email=f"user{user_id}@example.com", hashed_password="x", is_active=True, matches_last_seen_at=datetime.now(UTC)))
    # Viewer (id=1): male deck targeting women; candidates: women interested in men.
    if int(user_id) == 1:
        gender, interested_in, age = "male", "women", 29
    else:
        gender, interested_in, age = "female", "men", 27
    db.add(
        Profile(
            user_id=int(user_id),
            display_name=name,
            photo_urls="https://cdn.example.com/x.jpg",
            bio="bio bio bio bio bio",
            onboarding_completed=True,
            gender=gender,
            interested_in=interested_in,
            age=age,
        )
    )
    db.commit()


def test_swiped_card_still_appears_with_soft_ranking_on_cached_feed(monkeypatch):
    # Monkeypatch cache_get/cache_set + cache version to an in-memory store so we can test behavior without Redis.
    import app.api.v1.endpoints.discover as discover_mod

    store: dict[str, object] = {}
    version: dict[int, int] = {}

    def fake_get(key: str):
        return store.get(key)

    def fake_set(key: str, value: object, ttl_seconds: int):
        store[key] = value

    def fake_get_v(prefix: str, user_id: int) -> int:
        return int(version.get(int(user_id), 0))

    def fake_bump(prefix: str, user_id: int) -> int:
        version[int(user_id)] = int(version.get(int(user_id), 0)) + 1
        return version[int(user_id)]

    monkeypatch.setattr(discover_mod, "cache_get", fake_get)
    monkeypatch.setattr(discover_mod, "cache_set", fake_set)
    monkeypatch.setattr(discover_mod, "get_user_cache_version", fake_get_v)
    monkeypatch.setattr(discover_mod, "bump_user_cache_version", fake_bump)
    # Deterministic deck: avoid auto-seeded demo profiles outranking tiny synthetic fixtures.
    monkeypatch.setattr(discover_mod, "is_demo_mode_enabled", lambda _db: False)

    db = _memory_db()
    try:
        _seed_user_with_profile(db, 1, "A")
        _seed_user_with_profile(db, 2, "B")
        _seed_user_with_profile(db, 3, "C")
        client = _build_client(db, 1)

        r1 = client.get("/api/v1/discover/feed?limit=10&offset=0")
        assert r1.status_code == 200
        feed1 = r1.json()
        assert any(int(x["user_id"]) == 2 for x in feed1) or any(int(x["user_id"]) == 3 for x in feed1)
        first_id = int(feed1[0]["user_id"])

        # Swipe the first card.
        s = client.post("/api/v1/swipes", json={"target_user_id": first_id, "liked": False})
        assert s.status_code == 200

        r2 = client.get("/api/v1/discover/feed?limit=10&offset=0")
        assert r2.status_code == 200
        feed2 = r2.json()
        assert feed2
        # Soft-ranking mode: passed cards may still appear in feed.
        assert any(int(x["user_id"]) == first_id for x in feed2)
    finally:
        db.close()

