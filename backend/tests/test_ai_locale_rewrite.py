"""Strict AI localization rewrite checks (catalog, chains, leaks, demo bots)."""

from __future__ import annotations

import pytest

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.deps import get_current_user, get_db
from app.api.v1.endpoints.ai import _resolve_ai_locale_for_request, router as ai_router
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.constants.ai_surface_catalog import REQUIRED_SURFACE_KEYS, ai_surface_must, catalog_integrity_checked
from app.constants.supported_app_locales import ALL_SUPPORTED_APP_LOCALES
from app.db.base import Base
from app.models.profile import Profile
from app.models.user import User
from app.services.ai.ai_fallback_phrases import opener_typed_fallback
from app.services.ai.english_leak import ENGLISH_LEAK_MARKERS, english_leak_detected
from app.services.demo_bot_script import scripted_demo_message
from app.services.ai.locale_pipeline import AI_PROMPT_VERSION, resolve_ai_locale_strict_chain


@pytest.fixture(scope="module")
def mem_db_users():
    engine = create_engine(
        "sqlite://",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    db = Session(engine)
    u = User(email="rewrite@example.com", hashed_password="x", is_active=True)
    db.add(u)
    db.flush()
    db.add(
        Profile(
            user_id=int(u.id),
            display_name="Me",
            photo_urls="p.jpg",
            city="Kyiv",
            bio="bio",
            preferred_language="uk",
        )
    )
    db.commit()
    yield db, u
    db.close()


def test_catalog_integrity_all_locales():
    assert catalog_integrity_checked()
    for loc in ALL_SUPPORTED_APP_LOCALES:
        joined = "".join(ai_surface_must(loc, k) for k in REQUIRED_SURFACE_KEYS)
        if loc != "en":
            lower = joined.lower()
            assert not any(marker in lower for marker in ENGLISH_LEAK_MARKERS)


@pytest.mark.parametrize("locale_code", ALL_SUPPORTED_APP_LOCALES)
def test_demo_script_not_english(locale_code: str):
    pers = {"interests": ["coffee"], "personality": "warm", "flirt_level": 1}
    txt = scripted_demo_message(step=1, pers=pers, lang=locale_code, partner_name="Taylor")
    assert txt
    assert "?" in txt or "？" in txt
    if locale_code != "en":
        assert english_leak_detected(txt, locale=locale_code) is False


@pytest.mark.parametrize(
    "req,app_hdr,legacy,prof,accept,expect_lang,expect_src",
    [
        ("fr", "de", "", "", "", "fr", "request_body"),
        ("", "de", "", "uk", "es", "de", "x_app_locale"),
        ("", "", "pt", "uk", "", "pt", "ui_header"),
        ("", "", "", "pl", "es", "pl", "profile"),
        ("", "", "", "", "ar", "ar", "accept_language"),
        ("", "", "", "", "", "en", "fallback_en"),
        ("zh-CN", "", "", "", "", "zh", "request_body"),
    ],
)
def test_resolve_chain_v3(req, app_hdr, legacy, prof, accept, expect_lang, expect_src):
    loc, src = resolve_ai_locale_strict_chain(
        request_locale=req or None,
        app_locale_header=app_hdr or None,
        legacy_ui_locale=legacy or None,
        profile_locale=prof or None,
        accept_language_header=accept or None,
    )
    assert loc == expect_lang
    assert src == expect_src


def test_x_app_locale_headers_beat_profile(mem_db_users):
    db, u = mem_db_users

    class R:
        headers = {"X-App-Locale": "pt", "accept-language": "es-ES;q=0.9"}
        query_params = {}

    loc = _resolve_ai_locale_for_request(
        req_locale=None,
        ai_locale=None,
        request=R(),
        db=db,
        current_user=u,
        latest_user_message="hey",
        prefer_message_locale=False,
        route_label="test",
    )
    assert loc == "pt"


def test_ai_prompt_version_present():
    assert len(AI_PROMPT_VERSION) >= 6


def test_opener_phrases_no_common_leaks():
    for loc in ALL_SUPPORTED_APP_LOCALES:
        if loc == "en":
            continue
        joined = "".join(x[1] for x in opener_typed_fallback(loc))
        lower = joined.lower()
        assert not any(marker in lower for marker in ENGLISH_LEAK_MARKERS)


def test_timed_fallback_uses_app_locale(mem_db_users, monkeypatch):
    from app.core import config

    monkeypatch.setattr(config.settings, "ENABLE_AI_SUGGESTIONS", False)

    db, u = mem_db_users

    app = FastAPI()
    app.include_router(ai_router, prefix="/api/v1/ai")

    def _db():
        yield db

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_current_user] = lambda: u

    c = TestClient(app)
    r = c.post(
        "/api/v1/ai/timed-replies",
        headers={"X-App-Locale": "pt"},
        json={"messages": [{"role": "them", "text": "hey"}], "nudge_type": "reengage", "locale": ""},
    )
    assert r.status_code == 200
    assert r.json().get("locale") == "pt"


def test_surface_strings_for_matches_builder():
    for loc in ALL_SUPPORTED_APP_LOCALES:
        assert len(ai_surface_must(loc, "label_ai_match")) >= 2
        opener_typed_fallback(loc)
