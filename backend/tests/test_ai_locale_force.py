from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.deps import get_current_user, get_db
from app.api.v1.endpoints.ai import router as ai_router
from app.db.base import Base
from app.models.profile import Profile
from app.models.user import User
from app.services.ai.output_script_locale import text_matches_requested_locale
from app.services.ai.locale_decision import normalize_ai_locale_tag


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
    app.include_router(ai_router, prefix="/api/v1/ai")

    def _override_db():
        yield db

    def _override_user():
        return current_user

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_user] = _override_user
    return TestClient(app)


def _has_cyrillic(text: str) -> bool:
    return any("\u0400" <= ch <= "\u04FF" for ch in (text or ""))


@pytest.mark.parametrize("locale_tag", ["fr", "de", "es", "ar", "ja", "zh", "zh-TW", "uk", "en"])
def test_ai_opener_normalizes_ui_locale_tag_variants(monkeypatch, locale_tag: str):
    db = _memory_db()
    try:
        u = User(email=f"u-{locale_tag}@example.com", hashed_password="x", is_active=True)
        db.add(u)
        db.flush()
        db.add(Profile(user_id=int(u.id), display_name="Me", photo_urls="me.jpg", city="Kyiv", bio="hi"))
        db.commit()

        captured: dict[str, str] = {}

        class _MockProvider:
            async def opener_suggestions(self, **kwargs):
                captured["locale"] = str(kwargs.get("locale") or "")
                return {
                    "suggestions": [
                        {"type": "safe", "text": "Hey! What are you into lately?"},
                        {"type": "flirty", "text": "Quick question—what’s your kind of fun?"},
                        {"type": "smart", "text": "What’s something you’re learning right now?"},
                    ],
                    "recommended_index": 1,
                }

        monkeypatch.setattr("app.services.ai.service.get_ai_provider", lambda: _MockProvider())

        c = _client(db, u)
        r = c.post(
            "/api/v1/ai/opener",
            json={
                "match_name": "Alex",
                "bio": "",
                "interests": [],
                "city": "",
                "tags": [],
                "conversation_context": [],
                "style": "playful",
                "locale": locale_tag,
            },
        )
        assert r.status_code == 200
        assert captured.get("locale") == normalize_ai_locale_tag(locale_tag)

    finally:
        db.close()


def test_ai_opener_en_never_returns_cyrillic_even_if_provider_drifts(monkeypatch):
    db = _memory_db()
    try:
        u = User(email="u4@example.com", hashed_password="x", is_active=True)
        db.add(u)
        db.flush()
        db.add(Profile(user_id=int(u.id), display_name="Me", photo_urls="me.jpg", city="Kyiv", bio="hi"))
        db.commit()

        class _MockProvider:
            async def opener_suggestions(self, **kwargs):
                # Simulate the bug: provider returns Ukrainian while locale=en.
                return {
                    "suggestions": [
                        {"type": "safe", "text": "Привіт 🙂 Як пройшов твій день?"},
                        {"type": "flirty", "text": "Ти більше за каву чи вино? 😄"},
                        {"type": "smart", "text": "Що зараз тобі цікаво вчитись або пробувати?"},
                    ],
                    "recommended_index": 1,
                }

        monkeypatch.setattr("app.services.ai.service.get_ai_provider", lambda: _MockProvider())

        c = _client(db, u)
        r = c.post(
            "/api/v1/ai/opener",
            json={
                "match_name": "Alex",
                "bio": "",
                "interests": [],
                "city": "",
                "tags": [],
                "conversation_context": [],
                "style": "playful",
                "locale": "en",
            },
        )
        assert r.status_code == 200
        body = r.json()
        texts = []
        for row in (body.get("items") or [])[:3]:
            if isinstance(row, dict):
                texts.append(str(row.get("text") or ""))
        joined = " ".join(texts)
        assert not _has_cyrillic(joined)
    finally:
        db.close()


def test_ai_timed_replies_fallback_respects_locale_tag(monkeypatch):
    # Disable Gemini so we deterministically exercise fallback.
    from app.core import config

    monkeypatch.setattr(config.settings, "ENABLE_AI_SUGGESTIONS", False, raising=False)

    db = _memory_db()
    try:
        u = User(email="u2@example.com", hashed_password="x", is_active=True)
        db.add(u)
        db.flush()
        db.add(Profile(user_id=int(u.id), display_name="Me", photo_urls="me.jpg", city="Kyiv", bio="hi"))
        db.commit()

        c = _client(db, u)
        r = c.post(
            "/api/v1/ai/timed-replies",
            json={
                "messages": [{"role": "them", "text": "hey"}],
                "nudge_type": "now",
                "interest_stage": "warming",
                "mutuality_score": 40,
                "locale": "fr",
            },
        )
        assert r.status_code == 200
        rows = r.json().get("options") or []
        assert len(rows) == 3
        joined = " ".join([str(x.get("text") or "") for x in rows])
        assert not _has_cyrillic(joined)
    finally:
        db.close()


def test_ai_improve_reply_passes_through_ui_locale_tag(monkeypatch):
    db = _memory_db()
    try:
        u = User(email="u3@example.com", hashed_password="x", is_active=True)
        db.add(u)
        db.flush()
        db.add(Profile(user_id=int(u.id), display_name="Me", photo_urls="me.jpg", city="Kyiv", bio="hi"))
        db.commit()

        captured: dict[str, str] = {}

        class _MockProvider:
            async def improve_reply_draft(self, *args, **kwargs):
                captured["locale"] = str(kwargs.get("locale") or "")
                return {
                    "suggestions": [
                        {"text": "Sure—what do you mean exactly?", "style": "safe"},
                        {"text": "Got it. What’s the best-case scenario?", "style": "polish"},
                        {"text": "Interesting—can you tell me a bit more?", "style": "more_natural"},
                    ]
                }

        from app.core import config

        # Force the endpoint to call provider.improve_reply_draft path.
        monkeypatch.setattr(config.settings, "AI_PROVIDER", "gemini", raising=False)
        monkeypatch.setattr("app.services.ai.service.get_ai_provider", lambda: _MockProvider())

        c = _client(db, u)
        r = c.post(
            "/api/v1/ai/improve-reply",
            json={
                "draft": "Let’s do it.",
                "conversation_context": [],
                "user_style": "chill",
                "mode": "polish",
                "locale": "de",
            },
        )
        assert r.status_code == 200
        assert captured.get("locale") == "de"
        rows = r.json().get("variants") or []
        assert len(rows) >= 1
    finally:
        db.close()


def test_ai_timed_replies_fallback_french_normalizes_to_en():
    from app.core import config

    db = _memory_db()
    try:
        u = User(email="u-tr-fr@example.com", hashed_password="x", is_active=True)
        db.add(u)
        db.flush()
        db.add(Profile(user_id=int(u.id), display_name="Me", photo_urls="me.jpg", city="Kyiv", bio="hi"))
        db.commit()

        c = _client(db, u)
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(config.settings, "ENABLE_AI_SUGGESTIONS", False, raising=False)
            r = c.post(
                "/api/v1/ai/timed-replies",
                json={
                    "messages": [{"role": "them", "text": "hey"}],
                    "nudge_type": "reengage",
                    "locale": "fr",
                },
            )
        assert r.status_code == 200
        rows = r.json().get("options") or []
        joined = " ".join(str(x.get("text") or "") for x in rows)
        assert text_matches_requested_locale(joined, "en")
    finally:
        db.close()


@pytest.mark.parametrize("tag", [("zh"), ("zh-TW")])
def test_ai_timed_replies_zh_respects_requested_locale(tag: str):
    from app.core import config

    db = _memory_db()
    try:
        u = User(email=f"u-zh-{tag}@example.com", hashed_password="x", is_active=True)
        db.add(u)
        db.flush()
        db.add(Profile(user_id=int(u.id), display_name="Me", photo_urls="me.jpg", city="Kyiv", bio="hi"))
        db.commit()

        c = _client(db, u)
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(config.settings, "ENABLE_AI_SUGGESTIONS", False, raising=False)
            r = c.post(
                "/api/v1/ai/timed-replies",
                json={
                    "messages": [{"role": "them", "text": "hey"}],
                    "nudge_type": "reengage",
                    "locale": tag,
                },
            )
        assert r.status_code == 200
        rows = r.json().get("options") or []
        joined = " ".join(str(x.get("text") or "") for x in rows)
        assert (r.json() or {}).get("locale") == tag
        assert text_matches_requested_locale(joined, tag)
    finally:
        db.close()


def test_ai_timed_replies_arabic_respects_requested_locale():
    from app.core import config

    db = _memory_db()
    try:
        u = User(email="u-ar@example.com", hashed_password="x", is_active=True)
        db.add(u)
        db.flush()
        db.add(Profile(user_id=int(u.id), display_name="Me", photo_urls="me.jpg", city="Kyiv", bio="hi"))
        db.commit()

        c = _client(db, u)
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(config.settings, "ENABLE_AI_SUGGESTIONS", False, raising=False)
            r = c.post(
                "/api/v1/ai/timed-replies",
                json={
                    "messages": [{"role": "them", "text": "hey"}],
                    "nudge_type": "revive",
                    "locale": "ar",
                },
            )
        assert r.status_code == 200
        rows = r.json().get("options") or []
        joined = " ".join(str(x.get("text") or "") for x in rows)
        assert (r.json() or {}).get("locale") == "ar"
        assert text_matches_requested_locale(joined, "ar")
    finally:
        db.close()


def test_ai_improve_reply_defaults_to_en_when_locale_missing(monkeypatch):
    db = _memory_db()
    try:
        u = User(email="u-native-ru@example.com", hashed_password="x", is_active=True)
        db.add(u)
        db.flush()
        db.add(
            Profile(
                user_id=int(u.id),
                display_name="Me",
                photo_urls="me.jpg",
                city="Kyiv",
                bio="hi",
                native_language="ru",
            )
        )
        db.commit()

        class _MockProvider:
            async def improve_reply_draft(self, *args, **kwargs):
                return {
                    "suggestions": [
                        {"text": "Понял. Что для тебя важнее всего?", "style": "safe"},
                        {"text": "Интересно. Как ты это обычно решаешь?", "style": "polish"},
                        {"text": "Хорошая мысль. Что хочешь попробовать сначала?", "style": "more_natural"},
                    ]
                }

        from app.core import config

        monkeypatch.setattr(config.settings, "AI_PROVIDER", "gemini", raising=False)
        monkeypatch.setattr("app.services.ai.service.get_ai_provider", lambda: _MockProvider())

        c = _client(db, u)
        r = c.post(
            "/api/v1/ai/improve-reply",
            json={
                "draft": "test",
                "conversation_context": [],
                "user_style": "chill",
                "mode": "polish",
            },
        )
        assert r.status_code == 200
        meta = (r.json() or {}).get("meta") or {}
        assert meta.get("locale") == "en"
    finally:
        db.close()


def test_ai_timed_replies_defaults_to_en_when_locale_and_native_missing(monkeypatch):
    from app.core import config

    monkeypatch.setattr(config.settings, "ENABLE_AI_SUGGESTIONS", False, raising=False)
    db = _memory_db()
    try:
        u = User(email="u-locale-default-en@example.com", hashed_password="x", is_active=True)
        db.add(u)
        db.flush()
        db.add(Profile(user_id=int(u.id), display_name="Me", photo_urls="me.jpg", city="Kyiv", bio="hi", native_language=None))
        db.commit()
        c = _client(db, u)
        r = c.post(
            "/api/v1/ai/timed-replies",
            json={
                "messages": [{"role": "them", "text": "hey"}],
                "nudge_type": "now",
                "interest_stage": "warming",
                "mutuality_score": 40,
            },
        )
        assert r.status_code == 200
        assert (r.json() or {}).get("locale") == "en"
    finally:
        db.close()


def test_timed_replies_keeps_ui_locale_even_when_message_is_uk(monkeypatch):
    from app.core import config

    monkeypatch.setattr(config.settings, "ENABLE_AI_SUGGESTIONS", False, raising=False)
    db = _memory_db()
    try:
        u = User(email="u-msg-uk-over-ui-en@example.com", hashed_password="x", is_active=True)
        db.add(u)
        db.flush()
        db.add(Profile(user_id=int(u.id), display_name="Me", photo_urls="me.jpg", city="Kyiv", bio="hi"))
        db.commit()
        c = _client(db, u)
        r = c.post(
            "/api/v1/ai/timed-replies",
            json={
                "messages": [
                    {"role": "them", "text": "hello"},
                    {"role": "me", "text": "Привіт, як справи?"},
                ],
                "nudge_type": "now",
                "locale": "en",
            },
        )
        assert r.status_code == 200
        assert (r.json() or {}).get("locale") == "en"
    finally:
        db.close()


def test_timed_replies_keeps_ui_locale_even_when_message_is_en(monkeypatch):
    from app.core import config

    monkeypatch.setattr(config.settings, "ENABLE_AI_SUGGESTIONS", False, raising=False)
    db = _memory_db()
    try:
        u = User(email="u-msg-en-over-ui-uk@example.com", hashed_password="x", is_active=True)
        db.add(u)
        db.flush()
        db.add(Profile(user_id=int(u.id), display_name="Me", photo_urls="me.jpg", city="Kyiv", bio="hi"))
        db.commit()
        c = _client(db, u)
        r = c.post(
            "/api/v1/ai/timed-replies",
            json={
                "messages": [
                    {"role": "them", "text": "привіт"},
                    {"role": "me", "text": "Hey, how are you?"},
                ],
                "nudge_type": "now",
                "locale": "uk",
            },
        )
        assert r.status_code == 200
        assert (r.json() or {}).get("locale") == "uk"
    finally:
        db.close()


def test_coach_advice_french_not_english():
    from app.services.ai.coach_advice_locales import coach_advice_for_move

    t = coach_advice_for_move("wait", locale="fr")
    assert t and "Give it a little space" not in t
    assert "laisse" in t.lower()


def test_english_language_name_for_prompt_covers_locales():
    from app.services.ai.locale_prompt_language_names import english_language_name_for_ai_prompt

    assert "French" in english_language_name_for_ai_prompt("fr")
    assert "Chinese" in english_language_name_for_ai_prompt("zh-TW")
    assert "English" in english_language_name_for_ai_prompt("en")

