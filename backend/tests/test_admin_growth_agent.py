from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.deps import get_admin_user, get_admin_actor
from app.api.v1.endpoints.admin import router as admin_router
from app.db.session import SessionLocal
from app.models.profile import Profile
from app.models.user import User


class DummyAdmin:
    id = 999
    email = "admin@example.com"


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(admin_router, prefix="/api/v1/admin")
    app.dependency_overrides[get_admin_user] = lambda: DummyAdmin()
    app.dependency_overrides[get_admin_actor] = lambda: DummyAdmin()
    return TestClient(app)


def test_growth_overview_shape_and_period_filters():
    db = SessionLocal()
    try:
        now = datetime.now(UTC)
        u = User(email=f"growth_{int(now.timestamp())}@example.com", hashed_password=None, created_at=now)
        db.add(u)
        db.commit()
        db.refresh(u)
        db.add(Profile(user_id=u.id, display_name="GrowthUser", city="Kyiv", bio="", onboarding_completed=True, preferred_language="uk", country_code="UA"))

        old = now - timedelta(days=40)
        u2 = User(email=f"growth_old_{int(now.timestamp())}@example.com", hashed_password=None, created_at=old)
        db.add(u2)
        db.commit()
        db.refresh(u2)
        db.add(Profile(user_id=u2.id, display_name="Old", city="Kyiv", bio="", onboarding_completed=False, preferred_language="en", country_code="US"))
        db.commit()
    finally:
        db.close()

    c = _client()
    r_today = c.get("/api/v1/admin/growth/overview", params={"period": "today"})
    assert r_today.status_code == 200
    j = r_today.json()
    assert j["period"] == "today"
    for k in ["acquisition", "activation", "retention", "monetization", "recommendations", "onboarding"]:
        assert k in j
    assert "bottlenecks" in j["onboarding"] and "rates" in j["onboarding"]
    assert "new_users" in j["acquisition"]

    r_30 = c.get("/api/v1/admin/growth/overview", params={"period": "30d"})
    assert r_30.status_code == 200
    j30 = r_30.json()
    assert j30["period"] == "30d"
    # older user should not be counted in 30d new users
    assert int(j30["acquisition"]["new_users"]) >= 1


def test_growth_recommendations_shape_and_no_private_content():
    c = _client()
    r = c.get("/api/v1/admin/growth/recommendations")
    assert r.status_code == 200
    arr = r.json()
    assert isinstance(arr, list)
    for rec in arr[:5]:
        assert "title" in rec and "reason" in rec and "action" in rec
        # no per-user data
        assert "user" not in str(rec).lower()

