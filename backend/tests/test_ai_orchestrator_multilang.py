from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.profile import Profile
from app.services.ai.direct_questions import detect_direct_intent, render_direct_answer
from app.services.ai.orchestrator import AIOrchestrator


def test_spanish_direct_city_question():
    msg = "¿De qué ciudad eres?"
    assert detect_direct_intent(msg) == "city"
    p = Profile(display_name="Ana", city="Barcelona", preferred_language="es")
    out = render_direct_answer(
        speaker_profile=p,
        partner_profile=None,
        last_user_message=msg,
        ui_locale="es",
    )
    assert out
    low = out.lower()
    assert "barcelona" in low


def test_arabic_direct_age_question():
    msg = "كم عمرك؟"
    assert detect_direct_intent(msg) == "age"
    p = Profile(display_name="Sara", age=29, preferred_language="ar")
    out = render_direct_answer(speaker_profile=p, partner_profile=None, last_user_message=msg, ui_locale="ar")
    assert out and "29" in out


def test_german_hobby_question():
    msg = "Was sind deine Hobbys?"
    assert detect_direct_intent(msg) in {"hobbies", "interests"}
    p = Profile(display_name="Lena", interests="Lesen, Kochen", preferred_language="de")
    out = render_direct_answer(speaker_profile=p, partner_profile=None, last_user_message=msg, ui_locale="de")
    assert out
    low = out.lower()
    assert "lesen" in low or "koch" in low


def test_chinese_location_question():
    msg = "你住哪個城市？"
    assert detect_direct_intent(msg) == "city"
    p = Profile(display_name="Ming", city="上海", preferred_language="zh-CN")
    out = render_direct_answer(speaker_profile=p, partner_profile=None, last_user_message=msg, ui_locale="zh-CN")
    assert out
    assert "上海" in out


def test_gemini_improve_reply_falls_back_same_locale(monkeypatch: pytest.MonkeyPatch):
    from app.services.ai import diagnostics as diag

    diag.clear_gemini_cooldown()
    try:
        from app.core.config import settings

        monkeypatch.setattr(settings, "AI_PROVIDER", "gemini", raising=False)

        async def _boom(*_a, **_k):
            raise RuntimeError("429 RESOURCE_EXHAUSTED")

        mock_provider = MagicMock()
        mock_provider.improve_reply_draft = AsyncMock(side_effect=_boom)

        async def _run():
            with patch("app.services.ai.service.get_ai_provider", return_value=mock_provider):
                return await AIOrchestrator.run_improve_reply_core(
                    draft="Hola",
                    conversation_context=[],
                    user_style="chill",
                    allow_edgy_mode=False,
                    mode="polish",
                    plan_tier="free",
                    locale="es",
                    timeout_s=1.0,
                )

        rows = asyncio.run(_run())
        assert len(rows) >= 3
        joined = " ".join(str(r.get("text") or "") for r in rows)
        assert "qué" in joined.lower() or "¿" in joined or any(ord(c) > 127 for c in joined)
        assert "what do you like most about that" not in joined.lower()
    finally:
        diag.clear_gemini_cooldown()


def test_chat_brain_meta_premium_richer_than_free():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from sqlalchemy.pool import StaticPool

    from app.db.base import Base
    from app.models.user import User
    from app.services.ai.chat_brain_suggestions import ChatBrainRequest, run_chat_brain_suggestions

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db = Session(engine)
    try:
        u1 = User(email="a@a.com", hashed_password="x", is_active=True)
        u2 = User(email="b@b.com", hashed_password="x", is_active=True)
        db.add_all([u1, u2])
        db.flush()
        db.add(
            Profile(
                user_id=int(u1.id),
                display_name="A",
                preferred_language="en",
                city="X",
                onboarding_completed=True,
            )
        )
        db.add(Profile(user_id=int(u2.id), display_name="B", preferred_language="en", onboarding_completed=True))
        db.commit()
        body = ChatBrainRequest(partner_user_id=int(u2.id), mode="opener", language="en", conversation_mode="easy")
        free = run_chat_brain_suggestions(db, user_id=int(u1.id), body=body, plan_tier="free")
        prem = run_chat_brain_suggestions(db, user_id=int(u1.id), body=body, plan_tier="premium_plus")
        mf = (free.get("meta") or {}).get("tier_features") or {}
        mp = (prem.get("meta") or {}).get("tier_features") or {}
        assert mf.get("memory_in_prompt") is False
        assert mp.get("memory_in_prompt") is True
        assert mp.get("pickup_master_eligible") is True
        assert (free.get("meta") or {}).get("context_messages_limit", 0) < (prem.get("meta") or {}).get(
            "context_messages_limit", 0
        )
    finally:
        db.close()


def test_reply_suggestions_routes_via_orchestrator(monkeypatch: pytest.MonkeyPatch):
    called: dict[str, bool] = {}

    def _fake_gen(*, last_message: str, me, ui_locale=None):
        called["ok"] = True
        return ["a", "b", "c"]

    monkeypatch.setattr("app.services.ai.orchestrator.AIOrchestrator.generate_reply_suggestions", staticmethod(_fake_gen))
    from app.api.v1.endpoints import ai as ai_mod
    from app.core.config import settings

    monkeypatch.setattr(settings, "ENABLE_AI_SUGGESTIONS", True, raising=False)
    monkeypatch.setattr(settings, "ENABLE_PREMIUM_FEATURES", False, raising=False)
    monkeypatch.setattr(ai_mod, "enforce_ai_limits", lambda *_a, **_k: None)

    class _U:
        id = 1

    class _DB:
        def query(self, *_a, **_k):
            return self

        def filter(self, *_a, **_k):
            return self

        def first(self):
            return Profile(user_id=1, display_name="Me", preferred_language="en")

    out = ai_mod.reply_suggestions(payload={"last_message": "hi", "locale": "es"}, current_user=_U(), db=_DB())
    assert called.get("ok") and out.get("suggestions") == ["a", "b", "c"]


def test_icebreakers_use_orchestrator(monkeypatch: pytest.MonkeyPatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from sqlalchemy.pool import StaticPool

    from app.api.v1.endpoints import ai as ai_mod
    from app.core.config import settings
    from app.db.base import Base
    from app.models.user import User

    monkeypatch.setattr(settings, "ENABLE_AI_SUGGESTIONS", True, raising=False)
    monkeypatch.setattr(ai_mod, "enforce_ai_limits", lambda *_a, **_k: None)
    monkeypatch.setattr(
        "app.services.ai.orchestrator.AIOrchestrator.generate_icebreakers",
        staticmethod(lambda **kwargs: ["x1", "x2"]),
    )

    class SS:
        def get_active_plan(self, db, uid):
            return "premium"

    monkeypatch.setattr(ai_mod, "SubscriptionService", SS)

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db = Session(engine)
    try:
        u1 = User(email="a@a.com", hashed_password="x", is_active=True)
        u2 = User(email="b@b.com", hashed_password="x", is_active=True)
        db.add_all([u1, u2])
        db.flush()
        db.add(Profile(user_id=int(u1.id), display_name="Me", onboarding_completed=True))
        db.add(Profile(user_id=int(u2.id), display_name="Other", onboarding_completed=True))
        db.commit()

        class _U:
            id = int(u1.id)

        out = ai_mod.icebreakers(int(u2.id), current_user=_U(), db=db)
        assert out == {"suggestions": ["x1", "x2"]}
    finally:
        db.close()


def test_demo_reply_answer_before_vibe():
    from app.services.demo_mode import build_demo_reply

    p = Profile(display_name="D", city="Madrid", preferred_language="es")
    out = build_demo_reply(p, "¿De qué ciudad eres?", [])
    assert "madrid" in out.lower()
    playful_es = "qué te apasiona"
    assert playful_es not in out.lower()

