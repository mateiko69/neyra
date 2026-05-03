"""Paddle webhook → user subscription mirror."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.testclient import TestClient

from app.api.deps import get_db as deps_get_db
from app.db.base import Base
from app.main import app
from app.models.profile import Profile
from app.models.user import User
from app.services.monetization.plan_entitlements import entitlements_for_plan
from app.services.monetization.subscription_service import SubscriptionService
from app.services.monetization.subscription_sync import apply_subscription_mirror


@pytest.fixture()
def paddle_test_env():
    engine = create_engine(
        "sqlite://",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)

    def override_get_db():
        db = factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[deps_get_db] = override_get_db

    seed = factory()
    u = User(email="paddle_u@example.com", hashed_password="x", is_active=True, is_demo=False)
    seed.add(u)
    seed.commit()
    seed.refresh(u)
    seed.add(
        Profile(
            user_id=int(u.id),
            display_name="Paddle User",
            gender="woman",
            interested_in="men",
            photo_urls="a.jpg",
            city="Oslo",
            onboarding_completed=True,
        ),
    )
    seed.commit()
    uid = int(u.id)
    seed.close()

    try:
        with TestClient(app) as tc:
            yield tc, factory, uid
    finally:
        app.dependency_overrides.pop(deps_get_db, None)


def test_paddle_transaction_completed_does_not_activate_premium(paddle_test_env):
    tc, factory, uid = paddle_test_env
    payload = {
        "event_type": "transaction.completed",
        "event_id": "evt_txn",
        "data": {
            "id": "txn_test",
            "status": "completed",
            "customer_id": "ctm_txn",
            "email": "paddle_u@example.com",
            "items": [{"price": {"id": "pri_fake_premium"}}],
        },
    }
    r = tc.post("/api/v1/paddle/webhook", json=payload)
    assert r.status_code == 200, r.text
    assert r.json().get("skipped") is True
    db = factory()
    try:
        u2 = db.query(User).filter(User.id == int(uid)).first()
        assert u2 is not None
        assert u2.subscription_plan == "free"
        assert SubscriptionService().get_active_plan(db, uid) == "free"
    finally:
        db.close()


def test_paddle_webhook_idempotent_by_event_id(paddle_test_env):
    tc, factory, uid = paddle_test_env
    ends = (datetime.now(UTC) + timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%S.000000Z")
    payload = {
        "event_type": "subscription.updated",
        "event_id": "evt_same_id",
        "data": {
            "id": "sub_same",
            "status": "active",
            "customer_id": "ctm_1",
            "started_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "custom_data": {"user_id": str(uid), "plan_key": "premium_monthly"},
            "items": [{"price": {"id": "pri_fake_premium"}}],
            "current_billing_period": {"ends_at": ends},
        },
    }
    assert tc.post("/api/v1/paddle/webhook", json=payload).status_code == 200
    r2 = tc.post("/api/v1/paddle/webhook", json=payload)
    assert r2.status_code == 200
    assert r2.json().get("duplicate") is True


def test_paddle_subscription_webhook_updates_user_mirror(paddle_test_env):
    tc, factory, uid = paddle_test_env
    ends = (datetime.now(UTC) + timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%S.000000Z")

    payload = {
        "event_type": "subscription.updated",
        "event_id": "evt_test",
        "data": {
            "id": "sub_test",
            "status": "active",
            "customer_id": "ctm_1",
            "started_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "custom_data": {"user_id": str(uid), "plan_key": "premium_monthly"},
            "items": [{"price": {"id": "pri_fake_premium"}}],
            "current_billing_period": {"ends_at": ends},
        },
    }

    r = tc.post("/api/v1/paddle/webhook", json=payload)
    assert r.status_code == 200, r.text
    assert r.json().get("received") is True

    db = factory()
    try:
        u2 = db.query(User).filter(User.id == int(uid)).first()
        assert u2 is not None
        assert u2.subscription_plan == "premium"
        assert SubscriptionService().get_active_plan(db, uid) == "premium"
    finally:
        db.close()


def test_paddle_premium_plus_trialing_does_not_activate(paddle_test_env):
    """Only `active` may grant premium_plus; trialing is ignored (no mirror upgrade)."""
    tc, factory, uid = paddle_test_env
    ends = (datetime.now(UTC) + timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%S.000000Z")
    payload = {
        "event_type": "subscription.updated",
        "event_id": "evt_pp_trial",
        "data": {
            "id": "sub_pp_trial",
            "status": "trialing",
            "customer_id": "ctm_pp",
            "started_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "custom_data": {"user_id": str(uid), "plan_key": "premium_plus_monthly"},
            "items": [{"price": {"id": "pri_fake_plus"}}],
            "current_billing_period": {"ends_at": ends},
        },
    }
    r = tc.post("/api/v1/paddle/webhook", json=payload)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("skipped") is True
    assert body.get("reason") == "activation_policy"
    db = factory()
    try:
        u2 = db.query(User).filter(User.id == int(uid)).first()
        assert u2 is not None
        assert u2.subscription_plan == "free"
        assert SubscriptionService().get_active_plan(db, uid) == "free"
    finally:
        db.close()


def test_paddle_premium_trialing_subscription_created_grants_premium(paddle_test_env):
    tc, factory, uid = paddle_test_env
    ends = (datetime.now(UTC) + timedelta(days=5)).strftime("%Y-%m-%dT%H:%M:%S.000000Z")
    payload = {
        "event_type": "subscription.created",
        "event_id": "evt_prem_trial",
        "data": {
            "id": "sub_prem_trial",
            "status": "trialing",
            "customer_id": "ctm_prem",
            "started_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "custom_data": {"user_id": str(uid), "plan_key": "premium_monthly"},
            "items": [{"price": {"id": "pri_fake_premium"}}],
            "current_billing_period": {"ends_at": ends},
        },
    }
    r = tc.post("/api/v1/paddle/webhook", json=payload)
    assert r.status_code == 200, r.text
    assert r.json().get("received") is True
    db = factory()
    try:
        u2 = db.query(User).filter(User.id == int(uid)).first()
        assert u2 is not None
        assert u2.subscription_plan == "premium"
        assert str(u2.subscription_status or "").lower() == "trialing"
        assert SubscriptionService().get_active_plan(db, uid) == "premium"
    finally:
        db.close()


def test_subscription_downgrade_clears_entitlements():
    engine = create_engine("sqlite://", future=True)
    Base.metadata.create_all(engine)
    S = sessionmaker(bind=engine, future=True)
    db = S()
    try:
        u = User(email="d@example.com", hashed_password="x", is_active=True, is_demo=False)
        db.add(u)
        db.commit()
        db.refresh(u)
        until = datetime.now(UTC) + timedelta(days=2)
        apply_subscription_mirror(
            db,
            user_id=int(u.id),
            internal_plan="premium_plus",
            status="active",
            expires_at=until,
            provider="paddle",
            provider_subscription_id="s1",
        )
        assert SubscriptionService().get_active_plan(db, int(u.id)) == "premium_plus"
        apply_subscription_mirror(db, user_id=int(u.id), internal_plan="free", status="inactive", expires_at=None, provider="paddle")
        assert SubscriptionService().get_active_plan(db, int(u.id)) == "free"
        assert entitlements_for_plan("premium_plus").unlimited_ai is True
        assert entitlements_for_plan("free").unlimited_ai is False
    finally:
        db.close()


def test_ai_entitlements_daily_cap_matches_product():
    assert entitlements_for_plan("premium").ai_reply_daily_cap == 100
    assert entitlements_for_plan("premium_plus").unlimited_ai is True
