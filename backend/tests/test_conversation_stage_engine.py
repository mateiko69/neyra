from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.services.ai.conversation.conversation_stage_engine import (
    detect_stage,
    normalize_messages_for_stage,
    stage_ui_hints,
)


def test_opener_under_three_messages():
    out = detect_stage(
        [
            {"role": "me", "text": "Hey!"},
            {"role": "partner", "text": "Hi there"},
        ]
    )
    assert out["stage"] == "opener"
    assert 0 <= out["mutuality_score"] <= 1
    assert 0 <= out["energy_score"] <= 1


def test_engaged_when_shared_topic():
    msgs = [
        {"role": "me", "text": "Love travel on weekends"},
        {"role": "partner", "text": "Oh nice — I travel too"},
        {"role": "me", "text": "Where did you last go?"},
        {"role": "partner", "text": "Mostly short trips nearby"},
    ]
    out = detect_stage(msgs)
    assert out["stage"] == "engaged"


def test_meeting_ready_fast_replies_and_mutual():
    t0 = datetime.now(UTC)
    msgs = []
    for i in range(10):
        role = "me" if i % 2 == 0 else "partner"
        msgs.append(
            {
                "role": role,
                "text": f"msg{i} travel coffee meet" if i == 9 else f"msg{i} travel coffee",
                "created_at": t0 + timedelta(minutes=i * 5),
            }
        )
    out = detect_stage(msgs)
    assert out["stage"] == "meeting_ready"
    assert out["mutuality_score"] >= 0.5


def test_normalize_tuple_with_timestamp():
    t0 = datetime.now(UTC)
    norm = normalize_messages_for_stage([("me", "Hello", t0), ("them", "Hi back")])
    assert len(norm) == 2
    assert norm[0]["role"] == "me"
    assert norm[0]["created_at"] is not None


def test_stage_ui_hints():
    assert stage_ui_hints("flirty")[0] == "flirty"
