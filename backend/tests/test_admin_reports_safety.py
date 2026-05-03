from __future__ import annotations

from datetime import UTC, datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.deps import get_admin_user, get_admin_actor
from app.api.v1.endpoints.admin import router as admin_router
from app.db.session import SessionLocal
from app.models.profile import Profile
from app.models.user import User
from app.models.user_report import UserReport


class DummyAdmin:
    id = 999
    email = "admin@example.com"


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(admin_router, prefix="/api/v1/admin")
    app.dependency_overrides[get_admin_user] = lambda: DummyAdmin()
    app.dependency_overrides[get_admin_actor] = lambda: DummyAdmin()
    return TestClient(app)


def _seed_report(*, reporter_email: str, reported_email: str, reason: str, category: str = "spam") -> int:
    db = SessionLocal()
    try:
        rep = db.query(User).filter(User.email == reporter_email).first()
        if not rep:
            rep = User(email=reporter_email, hashed_password=None, created_at=datetime.now(UTC))
            db.add(rep)
            db.commit()
            db.refresh(rep)
            db.add(Profile(user_id=rep.id, display_name=reporter_email.split("@")[0], city="Kyiv"))
            db.commit()

        tgt = db.query(User).filter(User.email == reported_email).first()
        if not tgt:
            tgt = User(email=reported_email, hashed_password=None, created_at=datetime.now(UTC))
            db.add(tgt)
            db.commit()
            db.refresh(tgt)
            db.add(Profile(user_id=tgt.id, display_name=reported_email.split("@")[0], city="Kyiv"))
            db.commit()

        r = UserReport(reporter_id=rep.id, reported_user_id=tgt.id, reason=reason, category=category, status="open")
        db.add(r)
        db.commit()
        db.refresh(r)
        return int(r.id)
    finally:
        db.close()


def test_list_reports_and_detail_no_private_messages():
    rid = _seed_report(reporter_email="rep1@example.com", reported_email="tgt1@example.com", reason="spam: links", category="spam")
    c = _client()
    lst = c.get("/api/v1/admin/reports", params={"status": "open", "limit": 10, "offset": 0})
    assert lst.status_code == 200
    items = lst.json()
    assert any(int(x["report_id"]) == rid for x in items)

    det = c.get(f"/api/v1/admin/reports/{rid}")
    assert det.status_code == 200
    j = det.json()
    # safety: ensure no raw chat content keys
    dumped = str(j).lower()
    assert "message" not in dumped  # we should not expose raw messages in this endpoint
    assert "report" in j
    assert "moderation_recommendation" in j


def test_dismiss_and_resolve_require_confirm():
    rid = _seed_report(reporter_email="rep2@example.com", reported_email="tgt2@example.com", reason="harassment: rude", category="harassment")
    c = _client()
    bad = c.post(f"/api/v1/admin/reports/{rid}/dismiss", json={})
    assert bad.status_code == 400
    ok = c.post(f"/api/v1/admin/reports/{rid}/dismiss", json={"confirm": True})
    assert ok.status_code == 200

    rid2 = _seed_report(reporter_email="rep3@example.com", reported_email="tgt3@example.com", reason="scam: money", category="scam")
    bad2 = c.post(f"/api/v1/admin/reports/{rid2}/resolve", json={"action": "ban"})
    assert bad2.status_code == 400
    ok2 = c.post(f"/api/v1/admin/reports/{rid2}/resolve", json={"action": "ban", "confirm": True})
    assert ok2.status_code == 200

