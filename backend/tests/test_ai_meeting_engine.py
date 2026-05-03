from datetime import UTC, datetime, timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.deps import get_current_user, get_db
from app.api.v1.endpoints.ai import router as ai_router
from app.db.base import Base
from app.models.match import Match
from app.models.profile import Profile
from app.models.user import User
from app.models.user_block import UserBlock
from app.models.user_report import UserReport


def _memory_db() -> Session:
    engine = create_engine(
        "sqlite://",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return Session(engine)


def _create_user(db: Session, user_id: int) -> User:
    u = User(id=int(user_id), email=f"u{user_id}@example.com", hashed_password="x", is_active=True)
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _create_profile(db: Session, user_id: int, *, age: int = 25, city: str = "Kyiv", interests: str = "coffee,travel") -> Profile:
    p = Profile(user_id=int(user_id), display_name=f"User {user_id}", age=int(age), city=city, interests=interests)
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


def _create_match(db: Session, a: int, b: int) -> None:
    x, y = sorted([int(a), int(b)])
    db.add(Match(user_a_id=x, user_b_id=y))
    db.commit()


def _client(db: Session, me: User, monkeypatch) -> TestClient:
    # Avoid analytics writes during tests.
    from app.api.v1.endpoints import ai as ai_mod

    monkeypatch.setattr(ai_mod, "track_event", lambda *_a, **_k: None)
    monkeypatch.setattr(ai_mod, "get_redis", lambda: None)  # disable cooldown persistence for most tests

    app = FastAPI()
    app.include_router(ai_router, prefix="/api/v1/ai")

    app.dependency_overrides[get_current_user] = lambda: me

    def _override_db():
        yield db

    app.dependency_overrides[get_db] = _override_db
    return TestClient(app)


def _msgs(n: int, *, start_ms: int, step_ms: int = 60_000) -> list[dict]:
    out = []
    t = start_ms
    for i in range(n):
        role = "me" if i % 2 == 0 else "them"
        text = "That sounds fun 🙂 what do you like most?" if i % 3 == 0 else "Nice! tell me more?"
        out.append({"role": role, "text": text, "ts_ms": t})
        t += step_ms
    return out


def test_short_chat_never_suggests_meeting(monkeypatch):
    db = _memory_db()
    try:
        me = _create_user(db, 1)
        them = _create_user(db, 2)
        _create_profile(db, 1, age=25)
        _create_profile(db, 2, age=25)
        _create_match(db, 1, 2)
        client = _client(db, me, monkeypatch)
        now_ms = int(datetime.now(UTC).timestamp() * 1000)
        res = client.post(
            "/api/v1/ai/meeting-readiness",
            json={"partner_user_id": 2, "messages": _msgs(5, start_ms=now_ms - 5 * 60_000), "locale": "en"},
        )
        assert res.status_code == 200
        payload = res.json()
        assert payload["stage"] == "early"
        assert payload["score"] < 75
        assert payload["meeting_options"] == []
    finally:
        db.close()


def test_active_chat_suggests_meeting(monkeypatch):
    db = _memory_db()
    try:
        me = _create_user(db, 1)
        them = _create_user(db, 2)
        _create_profile(db, 1, age=25, city="Kyiv", interests="coffee,travel")
        _create_profile(db, 2, age=25, city="Kyiv", interests="coffee,books")
        _create_match(db, 1, 2)
        client = _client(db, me, monkeypatch)
        now_ms = int(datetime.now(UTC).timestamp() * 1000)
        res = client.post(
            "/api/v1/ai/meeting-readiness",
            json={"partner_user_id": 2, "messages": _msgs(16, start_ms=now_ms - 16 * 60_000), "locale": "en"},
        )
        assert res.status_code == 200
        payload = res.json()
        assert payload["stage"] == "ready"
        assert payload["score"] >= 75
        assert len(payload["meeting_options"]) == 3
        assert all("?" in str(o.get("text") or "") for o in payload["meeting_options"])
    finally:
        db.close()


def test_stalled_chat_suggests_revive(monkeypatch):
    db = _memory_db()
    try:
        me = _create_user(db, 1)
        them = _create_user(db, 2)
        _create_profile(db, 1, age=25)
        _create_profile(db, 2, age=25)
        _create_match(db, 1, 2)
        client = _client(db, me, monkeypatch)
        now_ms = int(datetime.now(UTC).timestamp() * 1000)
        old_ms = now_ms - int(timedelta(hours=13).total_seconds() * 1000)
        msgs = _msgs(10, start_ms=old_ms, step_ms=10_000)
        res = client.post("/api/v1/ai/meeting-readiness", json={"partner_user_id": 2, "messages": msgs, "locale": "en"})
        assert res.status_code == 200
        payload = res.json()
        assert payload["stage"] == "stalled"
        assert payload["suggested_action"] == "revive"
        assert payload["meeting_options"] == []
    finally:
        db.close()


def test_blocked_or_reported_never_suggests_meeting(monkeypatch):
    db = _memory_db()
    try:
        me = _create_user(db, 1)
        them = _create_user(db, 2)
        _create_profile(db, 1, age=25)
        _create_profile(db, 2, age=25)
        _create_match(db, 1, 2)
        # Block
        db.add(UserBlock(blocker_id=1, blocked_id=2))
        db.commit()
        client = _client(db, me, monkeypatch)
        now_ms = int(datetime.now(UTC).timestamp() * 1000)
        res = client.post(
            "/api/v1/ai/meeting-readiness",
            json={"partner_user_id": 2, "messages": _msgs(20, start_ms=now_ms - 20 * 60_000), "locale": "en"},
        )
        assert res.status_code == 200
        assert res.json()["meeting_options"] == []

        # Unblock + report
        db.query(UserBlock).delete()
        db.add(UserReport(reporter_id=1, reported_user_id=2, category="harassment", reason="x", status="open"))
        db.commit()
        res2 = client.post(
            "/api/v1/ai/meeting-readiness",
            json={"partner_user_id": 2, "messages": _msgs(20, start_ms=now_ms - 20 * 60_000), "locale": "en"},
        )
        assert res2.status_code == 200
        assert res2.json()["meeting_options"] == []
    finally:
        db.close()


def test_meeting_ready_endpoint_returns_score_and_suggestions(monkeypatch):
    db = _memory_db()
    try:
        me = _create_user(db, 1)
        _create_user(db, 2)
        _create_profile(db, 1, age=25, city="Kyiv", interests="coffee,travel")
        _create_profile(db, 2, age=25, city="Kyiv", interests="coffee,books")
        _create_match(db, 1, 2)
        client = _client(db, me, monkeypatch)
        now_ms = int(datetime.now(UTC).timestamp() * 1000)
        res = client.post(
            "/api/v1/ai/meeting-ready",
            json={"partner_user_id": 2, "messages": _msgs(10, start_ms=now_ms - 10 * 60_000), "locale": "en"},
        )
        assert res.status_code == 200
        body = res.json()
        assert "readiness_score" in body
        assert 0 <= int(body["readiness_score"]) <= 100
        assert "closer_stage" in body
        assert isinstance(body.get("suggestions"), list)
        assert len(body["suggestions"]) <= 3
    finally:
        db.close()


def test_localized_output(monkeypatch):
    db = _memory_db()
    try:
        me = _create_user(db, 1)
        them = _create_user(db, 2)
        _create_profile(db, 1, age=25, city="Київ")
        _create_profile(db, 2, age=25, city="Київ")
        _create_match(db, 1, 2)
        client = _client(db, me, monkeypatch)
        now_ms = int(datetime.now(UTC).timestamp() * 1000)
        for loc in ["uk", "ru", "es", "en"]:
            res = client.post(
                "/api/v1/ai/meeting-readiness",
                json={"partner_user_id": 2, "messages": _msgs(16, start_ms=now_ms - 16 * 60_000), "locale": loc},
            )
            assert res.status_code == 200
            payload = res.json()
            if loc in {"uk", "ru"}:
                joined = " ".join([o.get("text") or "" for o in payload.get("meeting_options") or []])
                assert any("\u0400" <= ch <= "\u04FF" for ch in joined)
            if loc == "es":
                joined = " ".join([o.get("text") or "" for o in payload.get("meeting_options") or []]).lower()
                assert "¿" in joined or "apetece" in joined
    finally:
        db.close()

