import pytest

from app.services.ai.structured import OpenersOut, RepliesOut, ConversationAnalysisOut, NextStepOut


def test_valid_json_models_accept():
    OpenersOut.model_validate(
        {"suggestions": [{"text": "Hey", "style": "playful", "reason": "shared interest"}, {"text": "Yo", "style": "confident", "reason": "bio"}, {"text": "Hi", "style": "fallback_safe", "reason": "safe"}]}
    )
    RepliesOut.model_validate({"suggestions": [{"text": "ok", "style": "safe"}, {"text": "cool", "style": "engaging"}, {"text": "nice", "style": "slightly_bold"}]})
    ConversationAnalysisOut.model_validate({"interest_level": 50, "response_quality": 55, "risk_of_drop": 40, "energy_level": "medium", "flags": []})
    NextStepOut.model_validate({"suggestions": ["ask deeper question"], "rationale": "signals"})


def test_invalid_openers_rejected():
    with pytest.raises(Exception):
        OpenersOut.model_validate({"suggestions": [{"text": "", "style": "playful", "reason": "x"}]})

