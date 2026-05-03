from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.analytics_event import AnalyticsEvent
from app.models.user import User
from app.models.user_ai_memory import UserAiMemory
from app.services import ab_engine
from app.services.ab_engine import (
    evaluate_experiments,
    record_metric,
    resolve_copy,
)


def _memory_session() -> Session:
    engine = create_engine(
        "sqlite://",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return Session(engine)


def _seed_user(db: Session, uid: int = 1) -> None:
    db.add(User(id=uid, email=f"u{uid}@example.com", hashed_password="x", is_active=True, is_demo=False))
    db.commit()


def test_resolve_assigns_sticky_variant() -> None:
    db = _memory_session()
    try:
        _seed_user(db, 1)
        r1 = resolve_copy(db, user_id=1, keys=["chat.opener.nudge"], record_exposure=False)
        r2 = resolve_copy(db, user_id=1, keys=["chat.opener.nudge"], record_exposure=False)
        assert r1["copy"]["chat.opener.nudge"]["variant_id"] == r2["copy"]["chat.opener.nudge"]["variant_id"]
        row = (
            db.query(UserAiMemory)
            .filter(UserAiMemory.user_id == 1, UserAiMemory.memory_type == "ab_variant", UserAiMemory.key == "chat.opener.nudge")
            .first()
        )
        assert row is not None
    finally:
        db.close()


def test_evaluate_promotes_winner_with_enough_signal() -> None:
    db = _memory_session()
    try:
        state = ab_engine._default_state()
        state["experiments"]["chat.opener.nudge"]["min_impressions_per_variant"] = 5
        state["experiments"]["chat.opener.nudge"]["min_relative_lift_vs_median"] = 0.01
        ab_engine._save_state(db, state)

        since = datetime.now(UTC) - timedelta(days=1)

        for i in range(5):
            db.add(
                AnalyticsEvent(
                    user_id=1,
                    name="ab_exposure",
                    payload_json=json.dumps({"experiment_key": "chat.opener.nudge", "variant_id": "v0", "round": 1}),
                    created_at=since,
                )
            )
        for i in range(5):
            db.add(
                AnalyticsEvent(
                    user_id=1,
                    name="ab_exposure",
                    payload_json=json.dumps({"experiment_key": "chat.opener.nudge", "variant_id": "v1", "round": 1}),
                    created_at=since,
                )
            )
        # v1 gets more successful downstream events
        for i in range(4):
            db.add(
                AnalyticsEvent(
                    user_id=1,
                    name="ab_message_sent",
                    payload_json=json.dumps({"experiment_key": "chat.opener.nudge", "variant_id": "v1", "round": 1}),
                    created_at=since,
                )
            )
        db.commit()

        out = evaluate_experiments(db)
        promoted = out.get("summary", {}).get("chat.opener.nudge", {}).get("promoted")
        assert promoted is True
    finally:
        db.close()


def test_record_metric_writes_analytics() -> None:
    db = _memory_session()
    try:
        _seed_user(db, 2)
        record_metric(db, user_id=2, experiment_key="paywall.message", variant_id="v2", metric="click")
        n = db.query(AnalyticsEvent).filter(AnalyticsEvent.name == "ab_click").count()
        assert n >= 1
    finally:
        db.close()
