from __future__ import annotations

from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.message import Message
from app.models.profile import Profile
from app.models.user import User
from app.services.ai.chat_brain_suggestions import ChatBrainRequest, run_chat_brain_suggestions


def _memory_db() -> Session:
    engine = create_engine(
        "sqlite://",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return Session(engine)


def test_chat_brain_fallback_answers_city_and_varies_endings(monkeypatch):
    # Force fallback (no Gemini) so we test non-provider behavior.
    import app.services.ai.gemini_client as gem

    monkeypatch.setattr(gem.GeminiClient, "enabled", classmethod(lambda cls: False))

    db = _memory_db()
    try:
        me = User(email="me@example.com", hashed_password="x", is_active=True)
        partner = User(email="p@example.com", hashed_password="x", is_active=True)
        db.add_all([me, partner])
        db.flush()
        db.add(Profile(user_id=int(me.id), display_name="Me", preferred_language="uk", city="Київ", age=26, onboarding_completed=True))
        db.add(Profile(user_id=int(partner.id), display_name="P", preferred_language="uk", city="Верховині", onboarding_completed=True))
        db.commit()

        # Partner asks a direct city question.
        db.add(
            Message(
                sender_id=int(partner.id),
                receiver_id=int(me.id),
                content="ти з якого міста?",
                is_demo_simulation=False,
            )
        )
        db.commit()

        out = run_chat_brain_suggestions(
            db,
            user_id=int(me.id),
            body=ChatBrainRequest(partner_user_id=int(partner.id), mode="reply", language="uk", conversation_mode="easy"),
            plan_tier="free",
        )
        assert out.get("ok") is True
        v = (out.get("variants") or {})
        light = str(v.get("light") or "").lower()
        assert ("ки" in light) or ("kyiv" in light)

        # Variation rule: not all variants should end with a question mark.
        texts = [str(v.get(k) or "").strip() for k in ("light", "flirty", "deep")]
        assert any(t and not t.endswith("?") for t in texts)
    finally:
        db.close()

