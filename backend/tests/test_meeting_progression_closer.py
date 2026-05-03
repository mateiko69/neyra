"""Meeting-soft ladder + closer_stage-aware timed fallbacks (no new endpoints)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta


def test_soft_meeting_ladder_uk_has_no_imperative_meet():
    from app.services.ai.conversation.closer_meeting import soft_meeting_ladder_three

    a, b, c = soft_meeting_ladder_three("uk")
    joined = f"{a} {b} {c}".lower()
    assert "давай зустрінемось" not in joined
    assert "кава" in b or "прогулянк" in b
    assert "😄" in a


def test_polish_timed_preserves_soft_lines_at_ready_for_meeting():
    from app.services.ai.conversation.closer_meeting import polish_timed_fallback_line

    line = "це вже звучить як розмова, яку краще продовжити не в чаті 😄"
    out = polish_timed_fallback_line(line, closer_stage="ready_for_meeting")
    assert not out.endswith("?")
    assert "😄" in out


def test_polish_timed_questions_non_ready():
    from app.services.ai.conversation.closer_meeting import polish_timed_fallback_line

    out = polish_timed_fallback_line("окей це цікаво", closer_stage="early_chat")
    assert out.endswith("?")


def test_closer_timed_replies_prompt_addon_includes_progression():
    from app.services.ai.conversation.closer_meeting import closer_timed_replies_prompt_addon

    s = closer_timed_replies_prompt_addon("engaged", "uk")
    assert "TIMED_REPLIES_PROGRESSION" in s
    assert "CONVERSATION_CLOSER" in s


def test_ready_for_meeting_fallback_matches_soft_ladder():
    from app.services.ai.conversation.closer_meeting import closer_copilot_fallback_lines, soft_meeting_ladder_three

    lines = closer_copilot_fallback_lines("uk", "ready_for_meeting", "останнє повідомлення", continue_mode=True)
    trip = soft_meeting_ladder_three("uk")
    assert lines[0] == trip[0]
    assert lines[1] == trip[1]
    assert lines[2] == trip[2]


def test_timed_replies_fallback_respects_closer_stage_ready():
    from app.api.v1.endpoints.ai import _timed_replies_fallback

    chat = [{"role": "them", "text": "привіт"}]
    rows, src = _timed_replies_fallback(
        chat,
        nudge_type="now",
        locale="uk",
        closer_stage="ready_for_meeting",
    )
    assert src == "uk"
    blob = " ".join(str(r.get("text") or "") for r in rows).lower()
    assert "давай зустрінемось" not in blob
    assert any("кава" in blob or "прогулянк" in blob for _ in (1,))


def test_chat_reaches_meeting_ready_stage_with_hints():
    """detect_stage needs ≥8 msgs, mutuality, meeting hint, and median gap ≤45m (needs timestamps)."""
    from app.services.ai.conversation.closer_meeting import compute_closer_stage

    base = datetime(2026, 5, 2, 10, 0, 0, tzinfo=UTC)
    chat = []
    for i in range(10):
        side = "me" if i % 2 == 0 else "them"
        t = (
            "Привіт 🙂 що ти любиш робити у вільний час?"
            if i == 0
            else "Я обожнюю прогулянки й подкасти, а ти?"
            if i == 1
            else "Згода, звучить як мій тип дня 🙂 розкажу ще про місто й маленькі кав’ярні?"
            if i == 2
            else f"Так, люблю такий темп і щоб було без фанфар 😄 трохи більше тексту для зв’язку {i}"
        )
        if i == 9:
            t = t + " maybe coffee sometime?"
        chat.append(
            {
                "role": side,
                "text": t,
                "created_at": (base + timedelta(minutes=12 * i)).isoformat(),
            }
        )
    cs, meta = compute_closer_stage(chat, stalled_chat=False)
    assert cs == "ready_for_meeting"
    assert meta.get("stage") == "meeting_ready"


def test_meeting_suggestions_no_imperative_phrases_all_locales():
    from app.services.ai.conversation.closer_meeting import closer_meeting_suggestions_three

    banned = ("давай зустрінемось", "давай встретимся", "let's meet")
    for loc in ("uk", "ru", "en"):
        lines = closer_meeting_suggestions_three(loc, "ready_for_meeting", city=None)
        blob = " ".join(lines).lower()
        for b in banned:
            assert b not in blob

