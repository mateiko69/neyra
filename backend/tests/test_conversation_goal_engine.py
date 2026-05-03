"""Conversation goal engine: meeting-driven heuristics."""

from __future__ import annotations

from app.services.ai.conversation_goal_engine import (
    compute_conversation_goal_state,
    premium_plus_goal_metrics_public,
)


def test_low_engagement_triggers_reengage():
    msgs = [
        {"role": "them", "text": "ok"},
        {"role": "me", "text": "Як ти?"},
        {"role": "them", "text": "норм"},
        {"role": "me", "text": "Що робиш?"},
        {"role": "them", "text": "нічого"},
    ]
    st = compute_conversation_goal_state(
        msgs,
        plan_tier="premium",
        locale="uk",
        interest_stage="cold",
        mutuality_score=25,
    )
    assert st.drop_risk > 60
    assert st.reengage_recommended is True


def test_high_engagement_allows_meeting_hint_for_plus():
    msgs = []
    for i in range(8):
        msgs.append(
            {"role": "them" if i % 2 else "me", "text": f"Message {i} - what do you think about weekend plans and coffee?"}
        )
    st = compute_conversation_goal_state(
        msgs,
        plan_tier="premium_plus",
        locale="en",
        mutuality_score=78,
        interest_stage="ready",
    )
    assert st.phase in {"comfort", "ready"}
    assert st.meeting_push_mode in {"soft_hint", "strong_hint"}
    assert st.drop_risk < 70


def test_longer_thread_increases_progress_vs_short():
    short = [
        {"role": "them", "text": "Hey!"},
        {"role": "me", "text": "Hi 🙂 how's your day going?"},
        {"role": "them", "text": "Pretty good, just finished work—yours?"},
    ]
    long = short + [
        {"role": "me", "text": "Same, a bit tired but good. What do you unwind with after work?"},
        {"role": "them", "text": "Usually a walk or a podcast—do you have a favorite show?"},
        {"role": "me", "text": "I bounce between comedy and history. Any topic you never get tired of?"},
        {"role": "them", "text": "Travel stories, always—have you been somewhere that surprised you?"},
        {"role": "me", "text": "Lisbon surprised me with the light. What city felt like 'you'?"},
    ]
    s_short = compute_conversation_goal_state(short, plan_tier="premium", locale="en")
    s_long = compute_conversation_goal_state(long, plan_tier="premium", locale="en")
    assert s_long.progress_score >= s_short.progress_score


def test_revive_nudge_raises_drop_risk_and_urgency():
    msgs = [
        {"role": "me", "text": "Still thinking about what you said 😊"},
        {"role": "them", "text": "oh cool"},
    ]
    idle = compute_conversation_goal_state(msgs, plan_tier="premium_plus", locale="en", nudge_type=None)
    revive = compute_conversation_goal_state(msgs, plan_tier="premium_plus", locale="en", nudge_type="revive")
    assert revive.drop_risk >= idle.drop_risk
    assert revive.urgency in {"high", "medium"}


def test_premium_plus_public_metrics_shape():
    msgs = [
        {"role": "them", "text": "Tell me more about you 🙂"},
        {"role": "me", "text": "I love hiking and quiet coffee shops—what's your ideal Sunday?"},
        {"role": "them", "text": "Brunch + a long walk, preferably somewhere new—do you explore the city often?"},
    ]
    st = compute_conversation_goal_state(msgs, plan_tier="premium_plus", locale="uk", mutuality_score=70)
    pub = premium_plus_goal_metrics_public(st, locale="uk")
    for k in ("best_next_move", "meeting_chance_percent", "risk_level", "phase", "urgency", "meeting_push_mode"):
        assert k in pub
    assert pub["risk_level"] in {"high", "medium", "low"}
