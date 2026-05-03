from app.services.growth_engine import GrowthEngine, GrowthMetrics


def test_growth_engine_decisions_cover_requested_logic():
    e = GrowthEngine()
    metrics = GrowthMetrics(
        onboarding_completion_rate=0.4,
        first_message_rate=0.2,
        reply_rate=0.4,
        dead_chats_count=120,
        matches_per_user=0.2,
    )
    actions = e.decide_actions(metrics)
    types = {a.action_type for a in actions if a.enabled}
    assert "enable_onboarding_nudges" in types
    assert "push_opener_suggestions" in types
    assert "activate_revive_system" in types
    assert "send_revive_prompts" in types

