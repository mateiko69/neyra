from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.deps import get_admin_user, get_admin_actor
from app.api.v1.endpoints.admin import router as admin_router
from app.core.config import settings


class DummyAdmin:
    id = 999
    email = "admin@example.com"


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(admin_router, prefix="/api/v1/admin")
    app.dependency_overrides[get_admin_user] = lambda: DummyAdmin()
    app.dependency_overrides[get_admin_actor] = lambda: DummyAdmin()
    return TestClient(app)


def test_premium_overview_shape():
    c = _client()
    res = c.get("/api/v1/admin/premium/overview")
    assert res.status_code == 200
    j = res.json()
    for k in [
        "trial_users",
        "premium_users",
        "expired_trials",
        "expiring_trials_24h",
        "expiring_trials_3d",
        "conversion_rate",
        "premium_revenue_best_effort",
        "top_paywall_sources",
    ]:
        assert k in j


def test_grant_all_dev_requires_confirm_and_blocked_in_production(monkeypatch):
    c = _client()
    res = c.post("/api/v1/admin/premium/grant-all-dev", json={"days": 30})
    assert res.status_code == 400

    monkeypatch.setattr(settings, "ENV", "production")
    res2 = c.post("/api/v1/admin/premium/grant-all-dev", json={"days": 30, "confirm": True})
    assert res2.status_code == 403
    monkeypatch.setattr(settings, "ENV", "development")


def test_promo_create_requires_confirm(monkeypatch):
    c = _client()
    res = c.post("/api/v1/admin/premium/create-promo-code", json={"code": "NEYRA_TEST", "days": 7, "max_uses": 10})
    assert res.status_code == 400

