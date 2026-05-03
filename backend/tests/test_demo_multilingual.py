from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import app.core.config as cfg
from app.db.base import Base
from app.models.match import Match
from app.models.message import Message
from app.models.profile import Profile
from app.models.user import User
from app.services import demo_behavior as dbh
from app.services.demo_mode import set_demo_live_settings, set_demo_mode_enabled


def _memory_session() -> Session:
    engine = create_engine(
        "sqlite://",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return Session(engine)


def _deliver_with_prefs(
    monkeypatch: pytest.MonkeyPatch,
    *,
    recipient_lang: str,
    opener_examples: dict | list,
) -> str:
    monkeypatch.setattr(cfg.settings, "DEMO_LIVE_BEHAVIOR", True)
    db = _memory_session()
    try:
        db.add(User(id=1, email="real@example.com", hashed_password="x", is_active=True, is_demo=False))
        db.add(User(id=2, email="demo@neyra.local", hashed_password=None, is_active=True, is_demo=True))
        db.add(
            Profile(
                user_id=1,
                display_name="Real",
                bio="",
                age=30,
                city="Kyiv",
                gender="man",
                interested_in="women",
                preferred_language=recipient_lang,
                onboarding_completed=True,
                is_demo_profile=False,
            )
        )
        pers = {
            "personality": "curious",
            "response_speed": "normal",
            "engagement_level": 0.8,
            "opener_examples": opener_examples,
            "reply_examples": opener_examples if isinstance(opener_examples, dict) else ["r"],
            "revive_examples": opener_examples if isinstance(opener_examples, dict) else ["v"],
        }
        db.add(
            Profile(
                user_id=2,
                display_name="Dee",
                bio="demo",
                age=25,
                city="Kyiv",
                gender="woman",
                interested_in="men",
                is_demo_profile=True,
                demo_personality_json=json.dumps(pers),
            )
        )
        db.add(Match(user_a_id=1, user_b_id=2))
        db.commit()
        set_demo_mode_enabled(db, True)
        set_demo_live_settings(db, enabled=True)
        p = db.query(Profile).filter(Profile.user_id == 2).first()
        dbh._set_pending(p, 1, "opener", datetime.now(UTC) - timedelta(seconds=5))
        db.add(p)
        db.commit()
        demo_u = db.query(User).filter(User.id == 2).first()
        dbh._deliver_pending(db, p, demo_u)
        m = db.query(Message).filter(Message.sender_id == 2, Message.receiver_id == 1).first()
        assert m is not None
        return str(m.content or "")
    finally:
        db.close()


def test_demo_opener_uses_uk_examples_for_uk_recipient(monkeypatch: pytest.MonkeyPatch) -> None:
    content = _deliver_with_prefs(
        monkeypatch,
        recipient_lang="uk",
        opener_examples={"en": ["Hello EN"], "uk": ["Привіт з каталогу УК"]},
    )
    assert "Привіт з каталогу УК" in content
    assert "Hello EN" not in content


def test_demo_opener_uses_en_examples_for_en_recipient(monkeypatch: pytest.MonkeyPatch) -> None:
    content = _deliver_with_prefs(
        monkeypatch,
        recipient_lang="en",
        opener_examples={"en": ["Hello EN opener"], "uk": ["Привіт УК"]},
    )
    assert "Hello EN opener" in content
    assert "Привіт УК" not in content


def test_demo_missing_locale_in_catalog_falls_back_to_en(monkeypatch: pytest.MonkeyPatch) -> None:
    content = _deliver_with_prefs(
        monkeypatch,
        recipient_lang="es",
        opener_examples={"en": ["Fallback EN for es"], "uk": ["УК"]},
    )
    assert "Fallback EN for es" in content


def test_chat_brain_receives_recipient_language(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, str] = {}

    def _fake_orchestrator(**kwargs):  # noqa: ANN001
        captured["language"] = str(kwargs.get("ui_locale"))
        return "Лінія без питання"

    monkeypatch.setattr("app.services.ai.orchestrator.AIOrchestrator.generate_demo_opener", staticmethod(_fake_orchestrator))
    monkeypatch.setattr(cfg.settings, "DEMO_LIVE_BEHAVIOR", True)
    db = _memory_session()
    try:
        db.add(User(id=1, email="real@example.com", hashed_password="x", is_active=True, is_demo=False))
        db.add(User(id=2, email="demo@neyra.local", hashed_password=None, is_active=True, is_demo=True))
        db.add(
            Profile(
                user_id=1,
                display_name="Real",
                bio="",
                age=30,
                city="Kyiv",
                gender="man",
                interested_in="women",
                preferred_language="uk",
                onboarding_completed=True,
                is_demo_profile=False,
            )
        )
        pers = {
            "personality": "warm",
            "response_speed": "normal",
            "engagement_level": 0.8,
            "opener_examples": {"en": [], "uk": []},
            "reply_examples": {"en": [], "uk": []},
            "revive_examples": {"en": [], "uk": []},
        }
        db.add(
            Profile(
                user_id=2,
                display_name="Dee",
                bio="demo",
                age=25,
                city="Kyiv",
                gender="woman",
                interested_in="men",
                is_demo_profile=True,
                demo_personality_json=json.dumps(pers),
            )
        )
        db.add(Match(user_a_id=1, user_b_id=2))
        db.commit()
        set_demo_mode_enabled(db, True)
        set_demo_live_settings(db, enabled=True)
        p = db.query(Profile).filter(Profile.user_id == 2).first()
        dbh._set_pending(p, 1, "reply", datetime.now(UTC) - timedelta(seconds=5))
        db.add(p)
        db.commit()
        demo_u = db.query(User).filter(User.id == 2).first()
        dbh._deliver_pending(db, p, demo_u)
        assert captured.get("language") == "uk"
        m = db.query(Message).filter(Message.sender_id == 2).first()
        assert m is not None
        body = str(m.content or "")
        assert " And you?" not in body
        assert "А ти?" in body
    finally:
        db.close()


def test_telegram_demo_live_strings_en_uk_parity() -> None:
    import importlib
    import sys

    scripts_dir = str(Path(__file__).resolve().parents[1] / "scripts")
    path_before = sys.path[:]
    sys.path.insert(0, scripts_dir)
    try:
        tab = importlib.import_module("telegram_admin_bot")
        strings = tab.STRINGS
    finally:
        sys.path[:] = path_before
        sys.modules.pop("telegram_admin_bot", None)

    en = strings["en"]
    uk = strings["uk"]
    keys = sorted(k for k in en if k.startswith("telegram.demo.live."))
    assert len(keys) >= 8
    for k in keys:
        assert k in uk
        assert str(en[k]).strip()
        assert str(uk[k]).strip()
