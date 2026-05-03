from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.deps import get_admin_user, get_admin_actor, get_db
from app.api.v1.endpoints.admin import router as admin_router
from app.db.base import Base
from app.models.analytics_event import AnalyticsEvent
from app.models.message import Message
from app.models.profile import Profile
from app.models.swipe import Swipe
from app.models.user import User


class DummyAdmin:
    id = 999
    email = "admin@example.com"


def _client() -> TestClient:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    import app.models  # noqa: F401
    Base.metadata.create_all(engine)

    def _get_db_override():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app = FastAPI()
    app.include_router(admin_router, prefix="/api/v1/admin")
    app.dependency_overrides[get_admin_user] = lambda: DummyAdmin()
    app.dependency_overrides[get_admin_actor] = lambda: DummyAdmin()
    app.dependency_overrides[get_db] = _get_db_override
    app.state.TestingSessionLocal = TestingSessionLocal  # type: ignore[attr-defined]
    return TestClient(app)


def test_stats_overview_shape_and_period_filters():
    c = _client()
    # Seed in the same in-memory DB the app uses via dependency override.
    db = c.app.state.TestingSessionLocal()  # type: ignore[attr-defined]
    try:
        now = datetime.now(UTC)
        u = User(email=f"stats_{int(now.timestamp())}@example.com", hashed_password=None, created_at=now)
        db.add(u)
        db.commit()
        db.refresh(u)
        db.add(Profile(user_id=u.id, display_name="StatsUser", city="Kyiv", bio="", onboarding_completed=True, verified=True))
        db.add(Swipe(swiper_id=u.id, target_user_id=u.id + 9999, liked=True, created_at=now))
        db.add(Message(sender_id=u.id, receiver_id=u.id + 9999, content="hi", created_at=now))
        db.add(AnalyticsEvent(user_id=u.id, name="ai_request_success", payload_json="{}", created_at=now))
        db.commit()

        old = now - timedelta(days=40)
        u2 = User(email=f"stats_old_{int(now.timestamp())}@example.com", hashed_password=None, created_at=old)
        db.add(u2)
        db.commit()
    finally:
        db.close()

    res = c.get("/api/v1/admin/stats/overview", params={"period": "today"})
    assert res.status_code == 200
    j = res.json()
    assert j["period"] == "today"
    for k in ["users", "dating", "ai", "premium", "safety"]:
        assert k in j
    assert j["users"]["new"] >= 1

    res2 = c.get("/api/v1/admin/stats/overview", params={"period": "7d"})
    assert res2.status_code == 200
    j2 = res2.json()
    assert j2["period"] == "7d"
    assert j2["users"]["new"] >= 1

