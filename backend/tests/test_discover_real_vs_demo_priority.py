from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.deps import get_current_user, get_db
from app.api.v1.endpoints.discover import router as discover_router
from app.api.v1.endpoints.dev import router as dev_router
from app.core.config import settings
from app.db.base import Base
from app.models.match import Match
from app.models.profile import Profile
from app.models.swipe import Swipe
from app.models.user import User
from app.services.demo_mode import set_demo_mode_enabled


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
    app.include_router(discover_router, prefix="/api/v1/discover")

    def _override_db():
        yield db

    def _override_user():
        return current_user

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_user] = _override_user
    return TestClient(app)


def test_discover_real_profiles_come_before_demo_when_both_exist():
    db = _memory_db()
    try:
        viewer = User(email="viewer@example.com", hashed_password="x", is_active=True, is_demo=False)
        real = User(email="real@example.com", hashed_password="x", is_active=True, is_demo=False)
        demo = User(email="demo@neyra.local", hashed_password=None, is_active=True, is_demo=True)
        db.add_all([viewer, real, demo])
        db.flush()
        set_demo_mode_enabled(db, True)

        db.add(
            Profile(
                user_id=int(viewer.id),
                display_name="Viewer",
                gender="woman",
                interested_in="men",
                min_preferred_age=18,
                max_preferred_age=80,
                photo_urls="v.jpg",
                age=26,
                native_language="en",
                onboarding_completed=True,
            )
        )
        db.add(
            Profile(
                user_id=int(real.id),
                display_name="Real",
                gender="man",
                interested_in="women",
                photo_urls="r.jpg",
                age=28,
                city="Kyiv",
                bio="hi",
                onboarding_completed=True,
            )
        )
        db.add(
            Profile(
                user_id=int(demo.id),
                display_name="Demo",
                gender="man",
                interested_in="women",
                photo_urls="d.jpg",
                age=27,
                city="Kyiv",
                bio="demo",
                onboarding_completed=True,
                is_demo_profile=True,
            )
        )
        db.commit()

        c = _client(db, viewer)
        r = c.get("/api/v1/discover/feed?limit=2&offset=0")
        assert r.status_code == 200
        rows = r.json() or []
        assert len(rows) >= 1
        # Real must come before demo in the returned deck.
        ids = [int(x.get("user_id") or 0) for x in rows if isinstance(x, dict)]
        assert int(real.id) in ids
        assert ids.index(int(real.id)) == 0
    finally:
        db.close()


def test_discover_demo_fallback_when_no_real_candidates():
    db = _memory_db()
    try:
        viewer = User(email="viewer2@example.com", hashed_password="x", is_active=True, is_demo=False)
        demo = User(email="demo2@neyra.local", hashed_password=None, is_active=True, is_demo=True)
        db.add_all([viewer, demo])
        db.flush()
        set_demo_mode_enabled(db, True)
        db.add(
            Profile(
                user_id=int(viewer.id),
                display_name="Viewer",
                photo_urls="v.jpg",
                onboarding_completed=True,
                gender="male",
                interested_in="women",
                age=28,
            )
        )
        db.add(
            Profile(
                user_id=int(demo.id),
                display_name="Demo",
                photo_urls="d.jpg",
                onboarding_completed=True,
                is_demo_profile=True,
                gender="female",
                interested_in="men",
                age=25,
            )
        )
        db.commit()

        c = _client(db, viewer)
        r = c.get("/api/v1/discover/feed?limit=1&offset=0")
        assert r.status_code == 200
        rows = r.json() or []
        assert len(rows) == 1
        assert bool(rows[0].get("is_demo_profile")) is True
    finally:
        db.close()


def test_discover_debug_candidate_returns_reason_for_gender_mismatch():
    db = _memory_db()
    try:
        viewer = User(email="viewer3@example.com", hashed_password="x", is_active=True, is_demo=False)
        cand = User(email="cand3@example.com", hashed_password="x", is_active=True, is_demo=False)
        db.add_all([viewer, cand])
        db.flush()
        set_demo_mode_enabled(db, False)
        db.add(Profile(user_id=int(viewer.id), display_name="Viewer", gender="woman", interested_in="men", photo_urls="v.jpg", onboarding_completed=True))
        db.add(Profile(user_id=int(cand.id), display_name="Cand", gender="woman", interested_in="women", photo_urls="c.jpg", onboarding_completed=True))
        db.commit()

        c = _client(db, viewer)
        r = c.get(f"/api/v1/discover/debug-candidate?candidate_user_id={int(cand.id)}")
        assert r.status_code == 200
        payload = r.json() or {}
        assert payload.get("eligible") is False
        reasons = set(payload.get("reasons") or [])
        assert "gender" in reasons
    finally:
        db.close()


def test_compatible_real_users_see_each_other():
    db = _memory_db()
    try:
        user_a = User(email="real-a@example.com", hashed_password="x", is_active=True, is_demo=False)
        user_b = User(email="real-b@example.com", hashed_password="x", is_active=True, is_demo=False)
        db.add_all([user_a, user_b])
        db.flush()
        set_demo_mode_enabled(db, False)
        db.add(
            Profile(
                user_id=int(user_a.id),
                display_name="Real A",
                gender="woman",
                interested_in="men",
                min_preferred_age=25,
                max_preferred_age=35,
                age=28,
                photo_urls="a.jpg",
                onboarding_completed=True,
            )
        )
        db.add(
            Profile(
                user_id=int(user_b.id),
                display_name="Real B",
                gender="man",
                interested_in="women",
                min_preferred_age=24,
                max_preferred_age=34,
                age=30,
                photo_urls="b.jpg",
                onboarding_completed=True,
            )
        )
        db.commit()

        c = _client(db, user_a)
        r = c.get("/api/v1/discover/feed?limit=5&offset=0")
        assert r.status_code == 200
        ids = [int(x.get("user_id") or 0) for x in (r.json() or []) if isinstance(x, dict)]
        assert int(user_b.id) in ids
    finally:
        db.close()


def test_compatible_real_users_still_visible_after_onboarding_save_state():
    db = _memory_db()
    try:
        user_a = User(email="organic-a@example.com", hashed_password="x", is_active=True, is_demo=False)
        user_b = User(email="organic-b@example.com", hashed_password="x", is_active=True, is_demo=False)
        db.add_all([user_a, user_b])
        db.flush()
        set_demo_mode_enabled(db, False)
        pa = Profile(
            user_id=int(user_a.id),
            display_name="A",
            gender="woman",
            interested_in="men",
            min_preferred_age=24,
            max_preferred_age=36,
            age=29,
            photo_urls="a.jpg",
            onboarding_completed=True,
        )
        pb = Profile(
            user_id=int(user_b.id),
            display_name="B",
            gender="man",
            interested_in="women",
            min_preferred_age=23,
            max_preferred_age=35,
            age=30,
            photo_urls="b.jpg",
            onboarding_completed=True,
        )
        db.add_all([pa, pb])
        db.commit()
        # Simulate profile save/update roundtrip after onboarding completion.
        pa.city = "Kyiv"
        db.add(pa)
        db.commit()
        c = _client(db, user_a)
        r = c.get("/api/v1/discover/feed?limit=5&offset=0")
        assert r.status_code == 200
        ids = [int(x.get("user_id") or 0) for x in (r.json() or []) if isinstance(x, dict)]
        assert int(user_b.id) in ids
    finally:
        db.close()


def test_gender_aliases_are_normalized_for_discover_matching():
    db = _memory_db()
    try:
        user_a = User(email="alias-a@example.com", hashed_password="x", is_active=True, is_demo=False)
        user_b = User(email="alias-b@example.com", hashed_password="x", is_active=True, is_demo=False)
        db.add_all([user_a, user_b])
        db.flush()
        set_demo_mode_enabled(db, False)
        db.add(
            Profile(
                user_id=int(user_a.id),
                display_name="Alias A",
                gender="female",
                interested_in="male",
                min_preferred_age=21,
                max_preferred_age=40,
                age=28,
                photo_urls="a.jpg",
                onboarding_completed=True,
            )
        )
        db.add(
            Profile(
                user_id=int(user_b.id),
                display_name="Alias B",
                gender="man",
                interested_in="women",
                min_preferred_age=20,
                max_preferred_age=34,
                age=29,
                photo_urls="b.jpg",
                onboarding_completed=True,
            )
        )
        db.commit()
        c = _client(db, user_a)
        r = c.get("/api/v1/discover/feed?limit=5&offset=0")
        assert r.status_code == 200
        ids = [int(x.get("user_id") or 0) for x in (r.json() or []) if isinstance(x, dict)]
        assert int(user_b.id) in ids
    finally:
        db.close()


def test_dev_discover_candidate_debug_breaks_down_real_profile_exclusions(monkeypatch):
    db = _memory_db()
    try:
        monkeypatch.setattr(settings, "DEV_TOOLS_ENABLED", True)
        viewer = User(email="debug-viewer@example.com", hashed_password="x", is_active=True, is_demo=False)
        candidate = User(email="debug-candidate@example.com", hashed_password="x", is_active=True, is_demo=False)
        db.add_all([viewer, candidate])
        db.flush()
        db.add(
            Profile(
                user_id=int(viewer.id),
                display_name="Viewer",
                gender="woman",
                interested_in="men",
                photo_urls="v.jpg",
                age=28,
                onboarding_completed=True,
            )
        )
        db.add(
            Profile(
                user_id=int(candidate.id),
                display_name="Candidate",
                gender="man",
                interested_in="women",
                photo_urls="",
                age=30,
                onboarding_completed=False,
            )
        )
        db.commit()

        app = FastAPI()
        app.include_router(dev_router, prefix="/api/v1/dev")

        def _override_db():
            yield db

        def _override_user():
            return viewer

        app.dependency_overrides[get_db] = _override_db
        app.dependency_overrides[get_current_user] = _override_user
        c = TestClient(app)
        r = c.get("/api/v1/dev/discover-candidate-debug")
        assert r.status_code == 200
        payload = r.json() or {}
        rows = payload.get("candidates") or []
        row = next(x for x in rows if int(x.get("user_id") or 0) == int(candidate.id))
        assert row["onboarding_completed"] is False
        assert row["gender_match"] is True
        assert row["age_match"] is True
        assert row["has_photo"] is False
        assert row["already_swiped"] is False
        assert row["blocked"] is False
        assert set(row["excluded_reasons"]) >= {"onboarding_completed", "has_photo"}
    finally:
        db.close()


def test_dev_discover_pair_debug_endpoint(monkeypatch):
    db = _memory_db()
    try:
        monkeypatch.setattr(settings, "DEV_TOOLS_ENABLED", True)
        user_a = User(email="pair-a@example.com", hashed_password="x", is_active=True, is_demo=False)
        user_b = User(email="pair-b@example.com", hashed_password="x", is_active=True, is_demo=False)
        db.add_all([user_a, user_b])
        db.flush()
        db.add(
            Profile(
                user_id=int(user_a.id),
                display_name="A",
                gender="woman",
                interested_in="men",
                age=28,
                min_preferred_age=24,
                max_preferred_age=35,
                photo_urls="a.jpg",
                onboarding_completed=True,
            )
        )
        db.add(
            Profile(
                user_id=int(user_b.id),
                display_name="B",
                gender="man",
                interested_in="women",
                age=29,
                min_preferred_age=20,
                max_preferred_age=32,
                photo_urls="b.jpg",
                onboarding_completed=True,
            )
        )
        db.commit()
        app = FastAPI()
        app.include_router(dev_router, prefix="/api/v1/dev")

        def _override_db():
            yield db

        def _override_user():
            return user_a

        app.dependency_overrides[get_db] = _override_db
        app.dependency_overrides[get_current_user] = _override_user
        c = TestClient(app)
        r = c.get(f"/api/v1/dev/discover-pair-debug?other_user_id={int(user_b.id)}")
        assert r.status_code == 200
        payload = r.json() or {}
        assert payload.get("should_see_each_other") is True
        assert payload.get("reasons_current_cannot_see_other") == []
        assert payload.get("reasons_other_cannot_see_current") == []
    finally:
        db.close()


def test_discover_strict_pair_real_candidate_beats_demo_fallback(monkeypatch):
    db = _memory_db()
    try:
        monkeypatch.setattr(settings, "DEV_TOOLS_ENABLED", True)
        viewer = User(email="strict-viewer@example.com", hashed_password="x", is_active=True, is_demo=False)
        real = User(email="strict-real@example.com", hashed_password="x", is_active=True, is_demo=False)
        demo = User(email="strict-demo@neyra.local", hashed_password=None, is_active=True, is_demo=True)
        db.add_all([viewer, real, demo])
        db.flush()
        set_demo_mode_enabled(db, True)
        db.add(
            Profile(
                user_id=int(viewer.id),
                display_name="Viewer",
                gender="woman",
                interested_in="men",
                min_preferred_age=18,
                max_preferred_age=50,
                age=29,
                photo_urls="viewer.jpg",
                onboarding_completed=True,
            )
        )
        db.add(
            Profile(
                user_id=int(real.id),
                display_name="Taras",
                gender="man",
                interested_in="women",
                min_preferred_age=18,
                max_preferred_age=50,
                age=37,
                photo_urls="real.jpg",
                onboarding_completed=True,
            )
        )
        db.add(
            Profile(
                user_id=int(demo.id),
                display_name="Demo Man",
                gender="man",
                interested_in="women",
                age=31,
                photo_urls="demo.jpg",
                onboarding_completed=True,
                is_demo_profile=True,
            )
        )
        db.commit()

        c = _client(db, viewer)
        r = c.get("/api/v1/discover/feed?limit=10&offset=0&include_debug=true")
        assert r.status_code == 200
        payload = r.json() or {}
        feed = payload.get("feed") or []
        debug = payload.get("debug") or {}
        ids = [int(x.get("user_id") or 0) for x in feed if isinstance(x, dict)]
        assert int(real.id) in ids
        assert debug.get("fallback_used") is False
        assert debug.get("fallback_stage") == "strict"
        assert bool(feed[0].get("is_demo_profile")) is False
    finally:
        db.close()


def test_discover_demo_fallback_respects_viewer_gender_interest():
    db = _memory_db()
    try:
        viewer_w = User(email="viewer-w@example.com", hashed_password="x", is_active=True, is_demo=False)
        demo_m = User(email="demo-m@neyra.local", hashed_password=None, is_active=True, is_demo=True)
        demo_w = User(email="demo-w@neyra.local", hashed_password=None, is_active=True, is_demo=True)
        db.add_all([viewer_w, demo_m, demo_w])
        db.flush()
        set_demo_mode_enabled(db, True)
        db.add(
            Profile(
                user_id=int(viewer_w.id),
                display_name="ViewerW",
                gender="woman",
                interested_in="men",
                age=29,
                photo_urls="viewerw.jpg",
                onboarding_completed=True,
            )
        )
        db.add(
            Profile(
                user_id=int(demo_m.id),
                display_name="DemoM",
                gender="man",
                interested_in="women",
                age=30,
                photo_urls="demom.jpg",
                onboarding_completed=True,
                is_demo_profile=True,
            )
        )
        db.add(
            Profile(
                user_id=int(demo_w.id),
                display_name="DemoW",
                gender="woman",
                interested_in="men",
                age=30,
                photo_urls="demow.jpg",
                onboarding_completed=True,
                is_demo_profile=True,
            )
        )
        db.commit()

        c_w = _client(db, viewer_w)
        r_w = c_w.get("/api/v1/discover/feed?limit=10&offset=0")
        assert r_w.status_code == 200
        rows_w = [x for x in (r_w.json() or []) if isinstance(x, dict)]
        assert rows_w
        assert all(str(x.get("gender") or "").strip().lower() in {"man", "male", "men", "guy", "m"} for x in rows_w)

        viewer_m = User(email="viewer-m@example.com", hashed_password="x", is_active=True, is_demo=False)
        db.add(viewer_m)
        db.flush()
        db.add(
            Profile(
                user_id=int(viewer_m.id),
                display_name="ViewerM",
                gender="man",
                interested_in="women",
                age=31,
                photo_urls="viewerm.jpg",
                onboarding_completed=True,
            )
        )
        db.commit()
        c_m = _client(db, viewer_m)
        r_m = c_m.get("/api/v1/discover/feed?limit=10&offset=0")
        assert r_m.status_code == 200
        rows_m = [x for x in (r_m.json() or []) if isinstance(x, dict)]
        assert rows_m
        assert all(str(x.get("gender") or "").strip().lower() in {"woman", "female", "women", "girl", "f"} for x in rows_m)
    finally:
        db.close()


def test_dev_discover_pair_debug_expected_clean_reasons(monkeypatch):
    db = _memory_db()
    try:
        monkeypatch.setattr(settings, "DEV_TOOLS_ENABLED", True)
        viewer = User(email="pair35@example.com", hashed_password="x", is_active=True, is_demo=False)
        other = User(email="pair9@example.com", hashed_password="x", is_active=True, is_demo=False)
        db.add_all([viewer, other])
        db.flush()
        db.add(
            Profile(
                user_id=int(viewer.id),
                display_name="Viewer35",
                gender="woman",
                interested_in="men",
                age=29,
                min_preferred_age=18,
                max_preferred_age=50,
                photo_urls="v35.jpg",
                onboarding_completed=True,
            )
        )
        db.add(
            Profile(
                user_id=int(other.id),
                display_name="Other9",
                gender="man",
                interested_in="women",
                age=37,
                min_preferred_age=18,
                max_preferred_age=50,
                photo_urls="o9.jpg",
                onboarding_completed=True,
            )
        )
        db.commit()

        app = FastAPI()
        app.include_router(dev_router, prefix="/api/v1/dev")

        def _override_db():
            yield db

        def _override_user():
            return viewer

        app.dependency_overrides[get_db] = _override_db
        app.dependency_overrides[get_current_user] = _override_user
        c = TestClient(app)
        r = c.get(f"/api/v1/dev/discover-pair-debug?other_user_id={int(other.id)}")
        assert r.status_code == 200
        payload = r.json() or {}
        assert payload.get("should_see_each_other") is True
        assert payload.get("reasons_current_cannot_see_other") == []
        assert payload.get("reasons_other_cannot_see_current") == []
    finally:
        db.close()


def test_discover_real_candidates_exist_no_demo_in_response():
    db = _memory_db()
    try:
        viewer = User(email="strict-only-viewer@example.com", hashed_password="x", is_active=True, is_demo=False)
        real = User(email="strict-only-real@example.com", hashed_password="x", is_active=True, is_demo=False)
        demo = User(email="strict-only-demo@neyra.local", hashed_password=None, is_active=True, is_demo=True)
        db.add_all([viewer, real, demo])
        db.flush()
        set_demo_mode_enabled(db, True)
        db.add(
            Profile(
                user_id=int(viewer.id),
                display_name="Viewer",
                gender="woman",
                interested_in="men",
                min_preferred_age=18,
                max_preferred_age=50,
                age=29,
                photo_urls="v.jpg",
                onboarding_completed=True,
            )
        )
        db.add(
            Profile(
                user_id=int(real.id),
                display_name="Real",
                gender="man",
                interested_in="women",
                min_preferred_age=18,
                max_preferred_age=50,
                age=33,
                photo_urls="r.jpg",
                onboarding_completed=True,
            )
        )
        db.add(
            Profile(
                user_id=int(demo.id),
                display_name="Demo",
                gender="man",
                interested_in="women",
                age=31,
                photo_urls="d.jpg",
                onboarding_completed=True,
                is_demo_profile=True,
            )
        )
        db.commit()
        c = _client(db, viewer)
        r = c.get("/api/v1/discover/feed?limit=10&offset=0")
        assert r.status_code == 200
        feed = [x for x in (r.json() or []) if isinstance(x, dict)]
        assert feed
        assert all(bool(x.get("is_demo_profile")) is False for x in feed)
        assert int(real.id) in [int(x.get("user_id") or 0) for x in feed]
    finally:
        db.close()


def test_discover_interested_in_men_never_returns_female_profiles():
    db = _memory_db()
    try:
        viewer = User(email="men-only-viewer@example.com", hashed_password="x", is_active=True, is_demo=False)
        real_ok = User(email="men-only-real@example.com", hashed_password="x", is_active=True, is_demo=False)
        demo_bad = User(email="men-only-demo-f@neyra.local", hashed_password=None, is_active=True, is_demo=True)
        db.add_all([viewer, real_ok, demo_bad])
        db.flush()
        set_demo_mode_enabled(db, True)
        db.add(
            Profile(
                user_id=int(viewer.id),
                display_name="Viewer",
                gender="woman",
                interested_in="men",
                age=29,
                min_preferred_age=18,
                max_preferred_age=50,
                photo_urls="v.jpg",
                onboarding_completed=True,
            )
        )
        db.add(
            Profile(
                user_id=int(real_ok.id),
                display_name="RealMan",
                gender="man",
                interested_in="women",
                age=34,
                min_preferred_age=18,
                max_preferred_age=50,
                photo_urls="r.jpg",
                onboarding_completed=True,
            )
        )
        db.add(
            Profile(
                user_id=int(demo_bad.id),
                display_name="DemoWoman",
                gender="woman",
                interested_in="men",
                age=30,
                photo_urls="d.jpg",
                onboarding_completed=True,
                is_demo_profile=True,
            )
        )
        db.commit()
        c = _client(db, viewer)
        r = c.get("/api/v1/discover/feed?limit=10&offset=0")
        assert r.status_code == 200
        feed = [x for x in (r.json() or []) if isinstance(x, dict)]
        assert feed
        genders = {str(x.get("gender") or "").strip().lower() for x in feed}
        assert genders.issubset({"man", "male", "men", "guy", "m"})
    finally:
        db.close()


def test_discover_debug_includes_new_interaction_and_demo_fields(monkeypatch):
    db = _memory_db()
    try:
        monkeypatch.setattr(settings, "DEV_TOOLS_ENABLED", True)
        viewer = User(email="debug-fields-viewer@example.com", hashed_password="x", is_active=True, is_demo=False)
        demo = User(email="debug-fields-demo@neyra.local", hashed_password=None, is_active=True, is_demo=True)
        db.add_all([viewer, demo])
        db.flush()
        set_demo_mode_enabled(db, True)
        db.add(
            Profile(
                user_id=int(viewer.id),
                display_name="Viewer",
                gender="woman",
                interested_in="men",
                age=28,
                photo_urls="v.jpg",
                onboarding_completed=True,
            )
        )
        db.add(
            Profile(
                user_id=int(demo.id),
                display_name="Demo",
                gender="woman",
                interested_in="men",
                age=30,
                photo_urls="d.jpg",
                onboarding_completed=True,
                is_demo_profile=True,
            )
        )
        db.add(Swipe(swiper_id=int(viewer.id), target_user_id=int(demo.id), liked=False))
        db.commit()
        c = _client(db, viewer)
        r = c.get("/api/v1/discover/feed?limit=10&offset=0&include_debug=true")
        assert r.status_code == 200
        payload = r.json() or {}
        debug = payload.get("debug") or {}
        assert "recycled_candidates_count" in debug
        assert "pass_cooldown_active" in debug
        assert "demo_filtered_by_gender" in debug
        assert "strict_real_ids" in debug
        assert "fallback_demo_ids" in debug
    finally:
        db.close()


def test_discover_passes_all_candidates_still_returns_profiles():
    db = _memory_db()
    try:
        viewer = User(email="pass-all-viewer@example.com", hashed_password="x", is_active=True, is_demo=False)
        c1 = User(email="pass-all-1@example.com", hashed_password="x", is_active=True, is_demo=False)
        c2 = User(email="pass-all-2@example.com", hashed_password="x", is_active=True, is_demo=False)
        db.add_all([viewer, c1, c2])
        db.flush()
        set_demo_mode_enabled(db, False)
        db.add(Profile(user_id=int(viewer.id), display_name="Viewer", gender="woman", interested_in="men", age=29, photo_urls="v.jpg", onboarding_completed=True))
        db.add(Profile(user_id=int(c1.id), display_name="C1", gender="man", interested_in="women", age=31, photo_urls="c1.jpg", onboarding_completed=True))
        db.add(Profile(user_id=int(c2.id), display_name="C2", gender="man", interested_in="women", age=33, photo_urls="c2.jpg", onboarding_completed=True))
        db.flush()
        db.add(Swipe(swiper_id=int(viewer.id), target_user_id=int(c1.id), liked=False))
        db.add(Swipe(swiper_id=int(viewer.id), target_user_id=int(c2.id), liked=False))
        db.commit()
        c = _client(db, viewer)
        r = c.get("/api/v1/discover/feed?limit=10&offset=0")
        assert r.status_code == 200
        rows = [x for x in (r.json() or []) if isinstance(x, dict)]
        assert len(rows) >= 1
    finally:
        db.close()


def test_discover_recent_pass_penalty_is_stronger_than_old_pass():
    db = _memory_db()
    try:
        viewer = User(email="penalty-viewer@example.com", hashed_password="x", is_active=True, is_demo=False)
        old_pass = User(email="penalty-old@example.com", hashed_password="x", is_active=True, is_demo=False)
        recent_pass = User(email="penalty-recent@example.com", hashed_password="x", is_active=True, is_demo=False)
        db.add_all([viewer, old_pass, recent_pass])
        db.flush()
        set_demo_mode_enabled(db, False)
        db.add(Profile(user_id=int(viewer.id), display_name="Viewer", gender="woman", interested_in="men", age=29, photo_urls="v.jpg", onboarding_completed=True))
        db.add(Profile(user_id=int(old_pass.id), display_name="Old", gender="man", interested_in="women", age=31, photo_urls="old.jpg", onboarding_completed=True))
        db.add(Profile(user_id=int(recent_pass.id), display_name="Recent", gender="man", interested_in="women", age=31, photo_urls="recent.jpg", onboarding_completed=True))
        db.flush()
        sw_old = Swipe(swiper_id=int(viewer.id), target_user_id=int(old_pass.id), liked=False)
        sw_recent = Swipe(swiper_id=int(viewer.id), target_user_id=int(recent_pass.id), liked=False)
        db.add_all([sw_old, sw_recent])
        db.commit()
        # Age old pass beyond cooldown.
        sw_old.created_at = sw_old.created_at.replace(year=sw_old.created_at.year - 1)
        db.add(sw_old)
        db.commit()
        c = _client(db, viewer)
        r = c.get("/api/v1/discover/feed?limit=1&offset=0")
        assert r.status_code == 200
        rows = [x for x in (r.json() or []) if isinstance(x, dict)]
        assert rows
        assert int(rows[0].get("user_id") or 0) == int(old_pass.id)
    finally:
        db.close()


def test_discover_match_still_removes_candidate():
    db = _memory_db()
    try:
        viewer = User(email="match-viewer@example.com", hashed_password="x", is_active=True, is_demo=False)
        other = User(email="match-other@example.com", hashed_password="x", is_active=True, is_demo=False)
        db.add_all([viewer, other])
        db.flush()
        set_demo_mode_enabled(db, False)
        db.add(Profile(user_id=int(viewer.id), display_name="Viewer", gender="woman", interested_in="men", age=29, photo_urls="v.jpg", onboarding_completed=True))
        db.add(Profile(user_id=int(other.id), display_name="Other", gender="man", interested_in="women", age=31, photo_urls="o.jpg", onboarding_completed=True))
        db.flush()
        db.add(Match(user_a_id=int(viewer.id), user_b_id=int(other.id)))
        db.commit()
        c = _client(db, viewer)
        r = c.get("/api/v1/discover/feed?limit=10&offset=0")
        assert r.status_code == 200
        ids = [int(x.get("user_id") or 0) for x in (r.json() or []) if isinstance(x, dict)]
        assert int(other.id) not in ids
    finally:
        db.close()


def test_discover_liked_candidate_is_hidden_by_penalty_when_alternatives_exist():
    db = _memory_db()
    try:
        viewer = User(email="like-viewer@example.com", hashed_password="x", is_active=True, is_demo=False)
        liked = User(email="like-liked@example.com", hashed_password="x", is_active=True, is_demo=False)
        fresh = User(email="like-fresh@example.com", hashed_password="x", is_active=True, is_demo=False)
        db.add_all([viewer, liked, fresh])
        db.flush()
        set_demo_mode_enabled(db, False)
        db.add(Profile(user_id=int(viewer.id), display_name="Viewer", gender="woman", interested_in="men", age=29, photo_urls="v.jpg", onboarding_completed=True))
        db.add(Profile(user_id=int(liked.id), display_name="Liked", gender="man", interested_in="women", age=31, photo_urls="l.jpg", onboarding_completed=True))
        db.add(Profile(user_id=int(fresh.id), display_name="Fresh", gender="man", interested_in="women", age=31, photo_urls="f.jpg", onboarding_completed=True))
        db.flush()
        db.add(Swipe(swiper_id=int(viewer.id), target_user_id=int(liked.id), liked=True))
        db.commit()
        c = _client(db, viewer)
        r = c.get("/api/v1/discover/feed?limit=1&offset=0")
        assert r.status_code == 200
        rows = [x for x in (r.json() or []) if isinstance(x, dict)]
        assert rows
        assert int(rows[0].get("user_id") or 0) == int(fresh.id)
    finally:
        db.close()


def test_reset_dating_state_clears_swipes_and_restores_candidate(monkeypatch):
    db = _memory_db()
    try:
        monkeypatch.setattr(settings, "DEV_TOOLS_ENABLED", True)
        viewer = User(email="reset-a@example.com", hashed_password="x", is_active=True, is_demo=False)
        other = User(email="reset-b@example.com", hashed_password="x", is_active=True, is_demo=False)
        db.add_all([viewer, other])
        db.flush()
        set_demo_mode_enabled(db, False)
        db.add(
            Profile(
                user_id=int(viewer.id),
                display_name="Viewer",
                gender="woman",
                interested_in="men",
                min_preferred_age=20,
                max_preferred_age=40,
                age=27,
                photo_urls="v.jpg",
                onboarding_completed=True,
            )
        )
        db.add(
            Profile(
                user_id=int(other.id),
                display_name="Other",
                gender="man",
                interested_in="women",
                min_preferred_age=20,
                max_preferred_age=40,
                age=28,
                photo_urls="o.jpg",
                onboarding_completed=True,
            )
        )
        db.flush()
        db.add(Swipe(swiper_id=int(viewer.id), target_user_id=int(other.id), liked=True))
        db.commit()
        c_discover = _client(db, viewer)
        r_before = c_discover.get("/api/v1/discover/feed?limit=10&offset=0")
        assert r_before.status_code == 200

        app = FastAPI()
        app.include_router(dev_router, prefix="/api/v1/dev")

        def _override_db():
            yield db

        def _override_user():
            return viewer

        app.dependency_overrides[get_db] = _override_db
        app.dependency_overrides[get_current_user] = _override_user
        c_dev = TestClient(app)
        rr = c_dev.post("/api/v1/dev/reset-dating-state")
        assert rr.status_code == 200
        assert rr.json().get("swipes_deleted", 0) >= 1

        r_after = c_discover.get("/api/v1/discover/feed?limit=10&offset=0")
        ids_after = [int(x.get("user_id") or 0) for x in (r_after.json() or []) if isinstance(x, dict)]
        assert int(other.id) in ids_after
    finally:
        db.close()
