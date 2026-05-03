"""Contextual deterministic UA fallback lines (intent buckets, no English leakage)."""

from __future__ import annotations

import re


def test_uk_weekend_question_has_weekend_tokens_and_no_english_leak():
    from app.services.ai.conversation.contextual_fallback_triples import uk_reply_fallback_three_lines

    q = "Окей, важливе питання 😄 як виглядають твої ідеальні вихідні?"
    lines = uk_reply_fallback_three_lines(q, continue_mode=True)
    joined = " ".join(lines)

    low = joined.lower()
    assert any(
        tok in low for tok in ("вихідн", "релакс", "актив", "прогулян", "каву", "видихнути", "емоцій")
    ), low

    jl = joined.lower()
    for snippet in ("what ", "yourself", "proud ", "genuinely", "playful"):
        assert snippet not in jl
    assert re.search(r"\bweekend\b", jl) is None
    assert re.search(r"\bdeeper\b", jl) is None


def test_uk_fallback_no_ascii_letters_when_bucket_weekend():
    from app.services.ai.conversation.contextual_fallback_triples import uk_reply_fallback_three_lines

    lines = uk_reply_fallback_three_lines("розкажеш як ти любиш проводити вихідні?", continue_mode=True)
    joined = " ".join(lines)
    assert not re.search(r"[A-Za-z]", joined), joined


def test_chat_brain_fallback_pack_uses_context_for_uk_weekend(monkeypatch):
    from app.services.ai.chat_brain_suggestions import fallback_pack

    out = fallback_pack("auto", "Оля", "uk", last_partner_message="Як у тебе ідеальні вихідні виглядають? 😄")
    text = " ".join(out.values()).lower()
    assert "вихідн" in text or "поїздк" in text, text


def test_wingman_strong_fallback_uses_matching_styles_and_uk_weekend_words():
    from app.application.use_cases.ai import wingman_replies as wr

    rows = wr._strong_fallback_triplet(
        "Ок 🙂 а як для тебе виглядають ідеальні вихідні?",
        locale="uk",
    )
    styles = [r["style"] for r in rows]
    assert styles == ["safe", "slightly_bold", "engaging"]

    blob = " ".join(str(r["text"]) for r in rows).lower()
    assert any(w in blob for w in ("вихідн", "релакс", "поїздк", "імпровізуєш")), blob


def test_timed_now_emergency_uk_matches_emergency_bank():
    from app.services.ai.ai_fallback_phrases import timed_now_emergency_triple
    from app.services.ai.conversation.contextual_fallback_triples import uk_emergency_fallback_triple

    assert timed_now_emergency_triple("uk") == uk_emergency_fallback_triple()


def test_guard_uk_variant_pack_strips_topic_brain_english():
    from app.services.ai.conversation.contextual_fallback_triples import guard_uk_variant_pack

    out = guard_uk_variant_pack(
        {
            "light": "Цікаво 🙂",
            "flirty": "Ок 🙂",
            "deep": "What's something you're proud of that sounds small out loud?",
        },
        last_partner_message="Окей 😄 як виглядають ідеальні вихідні?",
    )
    assert "proud" not in out["deep"].lower()
    assert "what" not in out["deep"].lower()
    assert "вихід" in out["deep"].lower() or "релакс" in out["deep"].lower()


def test_timed_replies_fallback_now_uk_source_and_cyrillic():
    from app.api.v1.endpoints.ai import _timed_replies_fallback

    chat = [{"role": "them", "text": "Окей, важливе питання 😄 як виглядають твої ідеальні вихідні?"}]
    rows, src = _timed_replies_fallback(chat, nudge_type="now", locale="uk")
    assert src == "uk"
    blob = " ".join(str(r.get("text") or "") for r in rows)
    assert not re.search(r"\b(what|proud|curious)\b", blob, re.I)


def test_topic_fallback_variant_uk_never_returns_general_seed_english():
    from app.services.ai.topic_brain import topic_fallback_variant

    lm = "Окей 😄 як виглядають ідеальні вихідні?"
    for variant in ("light", "flirty", "deep"):
        line = topic_fallback_variant("general", variant, "uk", last_partner_message=lm)
        assert not re.search(r"\b(what|proud|genuinely|yourself)\b", line, re.I), line
