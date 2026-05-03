"""Referral codes, invite links, signup attribution, claims, and reward milestones."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.deps import get_current_user, get_db
from app.api.v1.endpoints import auth, referrals
from app.core.security import get_password_hash
from app.db.base import Base
from app.models.analytics_event import AnalyticsEvent
from app.models.profile import Profile
from app.models.referral_reward_grant import ReferralRewardGrant
from app.models.user import User
from app.services.referrals import ensure_referral_code_for_user


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


def test_referrals_me_returns_code_and_invite_link():
    db = _memory_session()
    try:
        app = FastAPI()
        app.include_router(referrals.router, prefix="/api/v1/referrals")

        u = User(email="inv@example.com", hashed_password=get_password_hash("pw123456x"), is_active=True)
        db.add(u)
        db.commit()
        db.refresh(u)

        def _db():
            yield db

        app.dependency_overrides[get_db] = _db
        app.dependency_overrides[get_current_user] = lambda: u

        client = TestClient(app)
        r = client.get("/api/v1/referrals/me")
        assert r.status_code == 200
        data = r.json()
        assert data["referral_code"] and len(data["referral_code"]) >= 8
        assert "ref=" in data["invite_link"]
        assert data["referral_code"] in data["invite_link"]
        assert data["invites_count"] == 0
        assert data["joined_count"] == 0
        assert data["premium_rewards"] == []
        assert data["earned_rewards"] == []
        assert data["valid_referrals_count"] == 0
        assert data["next_reward"] is not None
        assert data["next_reward"]["required"] == 1
        assert data["next_reward"]["remaining"] == 1
    finally:
        db.close()


def test_register_with_referral_sets_referred_by_and_tracks_signup():
    db = _memory_session()
    try:
        app = FastAPI()
        app.include_router(auth.router, prefix="/api/v1/auth")

        def _db():
            yield db

        app.dependency_overrides[get_db] = _db

        inviter = User(email="inviter@example.com", hashed_password=get_password_hash("pw123456x"), is_active=True)
        db.add(inviter)
        db.flush()
        db.add(Profile(user_id=inviter.id, display_name="Inviter"))
        ensure_referral_code_for_user(db, inviter)
        db.commit()
        db.refresh(inviter)
        code = inviter.referral_code
        assert code

        client = TestClient(app)
        r = client.post(
            "/api/v1/auth/register",
            json={
                "email": "join@example.com",
                "password": "password1x",
                "display_name": "Joiner",
                "referral_code": code,
            },
        )
        assert r.status_code == 200, r.text
        joiner = db.query(User).filter(User.email == "join@example.com").first()
        assert joiner is not None
        assert joiner.referred_by_user_id == inviter.id
        ev = db.query(AnalyticsEvent).filter(AnalyticsEvent.name == "referral_signup_completed").first()
        assert ev is not None
        assert ev.user_id == joiner.id
    finally:
        db.close()


def test_claim_self_referral_blocked():
    db = _memory_session()
    try:
        app = FastAPI()
        app.include_router(referrals.router, prefix="/api/v1/referrals")

        u = User(email="self@example.com", hashed_password=get_password_hash("pw123456x"), is_active=True)
        db.add(u)
        db.commit()
        db.refresh(u)
        ensure_referral_code_for_user(db, u)
        db.commit()
        db.refresh(u)

        def _db():
            yield db

        app.dependency_overrides[get_db] = _db
        app.dependency_overrides[get_current_user] = lambda: u

        client = TestClient(app)
        r = client.post("/api/v1/referrals/claim", json={"referral_code": u.referral_code})
        assert r.status_code == 400
        assert _detail_code(r) == "referral.self"
    finally:
        db.close()


def test_claim_records_analytics():
    db = _memory_session()
    try:
        app = FastAPI()
        app.include_router(referrals.router, prefix="/api/v1/referrals")

        a = User(email="a@example.com", hashed_password=get_password_hash("pw123456x"), is_active=True)
        b = User(email="b@example.com", hashed_password=get_password_hash("pw123456x"), is_active=True)
        db.add(a)
        db.add(b)
        db.commit()
        db.refresh(a)
        db.refresh(b)
        ensure_referral_code_for_user(db, a)
        db.commit()
        db.refresh(a)

        def _db():
            yield db

        app.dependency_overrides[get_db] = _db
        app.dependency_overrides[get_current_user] = lambda: b

        client = TestClient(app)
        r = client.post("/api/v1/referrals/claim", json={"referral_code": a.referral_code})
        assert r.status_code == 200, r.text
        db.refresh(b)
        assert b.referred_by_user_id == a.id
        ev = db.query(AnalyticsEvent).filter(AnalyticsEvent.name == "referral_claimed", AnalyticsEvent.user_id == b.id).first()
        assert ev is not None
    finally:
        db.close()


def _app_auth_referrals(db: Session):
    app = FastAPI()
    app.include_router(auth.router, prefix="/api/v1/auth")
    app.include_router(referrals.router, prefix="/api/v1/referrals")

    def _db():
        yield db

    app.dependency_overrides[get_db] = _db
    return app


def test_three_valid_referrals_grants_seven_day_premium():
    db = _memory_session()
    try:
        app = _app_auth_referrals(db)
        inviter = User(email="inv7@example.com", hashed_password=get_password_hash("pw123456x"), is_active=True)
        db.add(inviter)
        db.flush()
        db.add(Profile(user_id=inviter.id, display_name="Inv"))
        ensure_referral_code_for_user(db, inviter)
        db.commit()
        db.refresh(inviter)
        code = inviter.referral_code
        client = TestClient(app)
        for i in range(3):
            r = client.post(
                "/api/v1/auth/register",
                json={
                    "email": f"join{i}@example.com",
                    "password": "password1x",
                    "display_name": f"J{i}",
                    "referral_code": code,
                },
            )
            assert r.status_code == 200, r.text
        db.refresh(inviter)
        assert inviter.premium_until is not None
        pu = inviter.premium_until
        if getattr(pu, "tzinfo", None) is None:
            pu = pu.replace(tzinfo=UTC)
        assert pu > datetime.now(UTC)
        r1 = db.query(ReferralRewardGrant).filter(ReferralRewardGrant.user_id == inviter.id, ReferralRewardGrant.milestone_key == "refs_1").first()
        assert r1 is not None
        assert r1.premium_days == 3
        r3 = db.query(ReferralRewardGrant).filter(ReferralRewardGrant.user_id == inviter.id, ReferralRewardGrant.milestone_key == "refs_3").first()
        assert r3 is not None
        assert r3.premium_days == 7
        ev = db.query(AnalyticsEvent).filter(AnalyticsEvent.name == "referral_premium_granted", AnalyticsEvent.user_id == inviter.id).first()
        assert ev is not None
    finally:
        db.close()


def test_ten_valid_referrals_grants_thirty_day_milestone():
    db = _memory_session()
    try:
        app = _app_auth_referrals(db)
        inviter = User(email="inv30@example.com", hashed_password=get_password_hash("pw123456x"), is_active=True)
        db.add(inviter)
        db.flush()
        db.add(Profile(user_id=inviter.id, display_name="Inv"))
        ensure_referral_code_for_user(db, inviter)
        db.commit()
        db.refresh(inviter)
        code = inviter.referral_code
        client = TestClient(app)
        for i in range(10):
            r = client.post(
                "/api/v1/auth/register",
                json={
                    "email": f"ten{i}@example.com",
                    "password": "password1x",
                    "display_name": f"T{i}",
                    "referral_code": code,
                },
            )
            assert r.status_code == 200, r.text
        rows = db.query(ReferralRewardGrant).filter(ReferralRewardGrant.user_id == inviter.id).all()
        keys = {r.milestone_key for r in rows}
        assert "refs_1" in keys
        assert "refs_3" in keys
        assert "refs_10" in keys
        r30 = db.query(ReferralRewardGrant).filter(ReferralRewardGrant.user_id == inviter.id, ReferralRewardGrant.milestone_key == "refs_10").first()
        assert r30 is not None
        assert r30.premium_days == 30
    finally:
        db.close()


def test_demo_referred_user_does_not_count_for_reward():
    db = _memory_session()
    try:
        app = _app_auth_referrals(db)
        inviter = User(email="invd@example.com", hashed_password=get_password_hash("pw123456x"), is_active=True)
        db.add(inviter)
        db.flush()
        db.add(Profile(user_id=inviter.id, display_name="Inv"))
        ensure_referral_code_for_user(db, inviter)
        db.commit()
        db.refresh(inviter)
        code = inviter.referral_code
        client = TestClient(app)
        for i in range(2):
            r = client.post(
                "/api/v1/auth/register",
                json={
                    "email": f"rd{i}@example.com",
                    "password": "password1x",
                    "display_name": f"R{i}",
                    "referral_code": code,
                },
            )
            assert r.status_code == 200, r.text
        demo_u = User(
            email="demojoin@example.com",
            hashed_password=get_password_hash("pw123456x"),
            is_active=True,
            is_demo=True,
            referred_by_user_id=inviter.id,
        )
        db.add(demo_u)
        db.flush()
        db.add(Profile(user_id=demo_u.id, display_name="Demo"))
        db.commit()
        db.refresh(inviter)
        assert db.query(ReferralRewardGrant).filter(ReferralRewardGrant.user_id == inviter.id, ReferralRewardGrant.milestone_key == "refs_3").first() is None
        assert db.query(ReferralRewardGrant).filter(ReferralRewardGrant.user_id == inviter.id, ReferralRewardGrant.milestone_key == "refs_1").first() is not None
        r = client.post(
            "/api/v1/auth/register",
            json={
                "email": "thirdreal@example.com",
                "password": "password1x",
                "display_name": "Third",
                "referral_code": code,
            },
        )
        assert r.status_code == 200, r.text
        db.refresh(inviter)
        assert db.query(ReferralRewardGrant).filter(ReferralRewardGrant.user_id == inviter.id, ReferralRewardGrant.milestone_key == "refs_3").first() is not None
    finally:
        db.close()


def test_banned_referred_user_does_not_count():
    db = _memory_session()
    try:
        app = _app_auth_referrals(db)
        inviter = User(email="invb@example.com", hashed_password=get_password_hash("pw123456x"), is_active=True)
        db.add(inviter)
        db.flush()
        db.add(Profile(user_id=inviter.id, display_name="Inv"))
        ensure_referral_code_for_user(db, inviter)
        db.commit()
        db.refresh(inviter)
        code = inviter.referral_code
        client = TestClient(app)
        for i in range(2):
            assert (
                client.post(
                    "/api/v1/auth/register",
                    json={
                        "email": f"rb{i}@example.com",
                        "password": "password1x",
                        "display_name": f"R{i}",
                        "referral_code": code,
                    },
                ).status_code
                == 200
            )
        ban_u = User(
            email="bannedjoin@example.com",
            hashed_password=get_password_hash("pw123456x"),
            is_active=True,
            is_banned=True,
            referred_by_user_id=inviter.id,
        )
        db.add(ban_u)
        db.flush()
        db.add(Profile(user_id=ban_u.id, display_name="Ban"))
        db.commit()
        db.refresh(inviter)
        assert db.query(ReferralRewardGrant).filter(ReferralRewardGrant.user_id == inviter.id, ReferralRewardGrant.milestone_key == "refs_3").first() is None
        assert db.query(ReferralRewardGrant).filter(ReferralRewardGrant.user_id == inviter.id, ReferralRewardGrant.milestone_key == "refs_1").first() is not None
        assert (
            client.post(
                "/api/v1/auth/register",
                json={
                    "email": "thirdban@example.com",
                    "password": "password1x",
                    "display_name": "T3",
                    "referral_code": code,
                },
            ).status_code
            == 200
        )
        db.refresh(inviter)
        assert db.query(ReferralRewardGrant).filter(ReferralRewardGrant.user_id == inviter.id, ReferralRewardGrant.milestone_key == "refs_3").first() is not None
    finally:
        db.close()


def test_inviter_banned_does_not_receive_rewards():
    db = _memory_session()
    try:
        app = _app_auth_referrals(db)
        inviter = User(email="invban@example.com", hashed_password=get_password_hash("pw123456x"), is_active=True)
        db.add(inviter)
        db.flush()
        db.add(Profile(user_id=inviter.id, display_name="Inv"))
        ensure_referral_code_for_user(db, inviter)
        db.commit()
        db.refresh(inviter)
        inviter.is_banned = True
        db.add(inviter)
        db.commit()
        code = inviter.referral_code
        client = TestClient(app)
        for i in range(3):
            assert (
                client.post(
                    "/api/v1/auth/register",
                    json={
                        "email": f"ib{i}@example.com",
                        "password": "password1x",
                        "display_name": f"I{i}",
                        "referral_code": code,
                    },
                ).status_code
                == 200
            )
        db.refresh(inviter)
        assert db.query(ReferralRewardGrant).filter(ReferralRewardGrant.user_id == inviter.id).first() is None
    finally:
        db.close()


def test_gmail_alias_fingerprint_counts_once():
    db = _memory_session()
    try:
        app = _app_auth_referrals(db)
        inviter = User(email="invfp@example.com", hashed_password=get_password_hash("pw123456x"), is_active=True)
        db.add(inviter)
        db.flush()
        db.add(Profile(user_id=inviter.id, display_name="Inv"))
        ensure_referral_code_for_user(db, inviter)
        db.commit()
        db.refresh(inviter)
        code = inviter.referral_code
        client = TestClient(app)
        for em in ("abuse@gmail.com", "abuse+1@gmail.com", "abuse+2@gmail.com"):
            assert client.post(
                "/api/v1/auth/register",
                json={"email": em, "password": "password1x", "display_name": "A", "referral_code": code},
            ).status_code == int(200)
        db.refresh(inviter)
        assert db.query(ReferralRewardGrant).filter(ReferralRewardGrant.user_id == inviter.id, ReferralRewardGrant.milestone_key == "refs_1").first() is not None
        assert db.query(ReferralRewardGrant).filter(ReferralRewardGrant.user_id == inviter.id, ReferralRewardGrant.milestone_key == "refs_3").first() is None
    finally:
        db.close()


def test_claim_reward_idempotent_after_auto_grant():
    db = _memory_session()
    try:
        app = _app_auth_referrals(db)
        inviter = User(email="invc@example.com", hashed_password=get_password_hash("pw123456x"), is_active=True)
        db.add(inviter)
        db.flush()
        db.add(Profile(user_id=inviter.id, display_name="Inv"))
        ensure_referral_code_for_user(db, inviter)
        db.commit()
        db.refresh(inviter)
        code = inviter.referral_code
        client = TestClient(app)
        for i in range(3):
            assert (
                client.post(
                    "/api/v1/auth/register",
                    json={
                        "email": f"ic{i}@example.com",
                        "password": "password1x",
                        "display_name": f"I{i}",
                        "referral_code": code,
                    },
                ).status_code
                == 200
            )
        app.dependency_overrides[get_current_user] = lambda: inviter
        r = client.post("/api/v1/referrals/claim-reward")
        assert r.status_code == 200
        assert r.json().get("status") == "no_reward_available"
    finally:
        db.close()
