from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.services.ai.conversation.dating_strategy_engine import plan_dating_strategy


def test_opener_continue_low_pressure():
    st = {"stage": "opener", "mutuality_score": 0.2, "energy_score": 0.3}
    out = plan_dating_strategy(
        stage_info=st,
        stage_messages=[{"role": "me", "text": "Hey"}],
        last_text_role="partner",
        hours_since_last_text=0.5,
        run_generation=True,
        trail_me=0,
    )
    assert out["next_action"] == "continue"
    assert "low_pressure" in out["reasoning_tags"]


def test_meeting_ready_suggest_meet():
    st = {"stage": "meeting_ready", "mutuality_score": 0.72, "energy_score": 0.6}
    t0 = datetime.now(UTC)
    msgs = [{"role": "me" if i % 2 == 0 else "partner", "text": "x", "created_at": t0 + timedelta(minutes=i * 4)} for i in range(10)]
    out = plan_dating_strategy(
        stage_info=st,
        stage_messages=msgs,
        last_text_role="partner",
        hours_since_last_text=0.1,
        run_generation=True,
        trail_me=0,
    )
    assert out["next_action"] == "suggest_meet"
    assert "meeting_window" in out["reasoning_tags"]


def test_wait_when_not_run_generation():
    st = {"stage": "engaged", "mutuality_score": 0.6, "energy_score": 0.5}
    out = plan_dating_strategy(
        stage_info=st,
        stage_messages=[],
        last_text_role="me",
        hours_since_last_text=0.01,
        run_generation=False,
        trail_me=0,
    )
    assert out["next_action"] == "wait"
    assert "cooling_off" in out["reasoning_tags"]


def test_wait_double_text():
    st = {"stage": "warmup", "mutuality_score": 0.5, "energy_score": 0.4}
    out = plan_dating_strategy(
        stage_info=st,
        stage_messages=[{"role": "me", "text": "a"}, {"role": "me", "text": "b"}],
        last_text_role="me",
        hours_since_last_text=0.5,
        run_generation=True,
        trail_me=2,
    )
    assert out["next_action"] == "wait"
