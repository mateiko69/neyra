from app.services.trust.profile_risk_evaluator import ProfileRiskEvaluator
from app.services.fraud.scam_signal_detector import ScamSignalDetector
from app.services.moderation.conversation_quality_evaluator import ConversationQualityEvaluator
from app.services.moderation.message_risk_evaluator import MessageRiskEvaluator
from app.services.trust.bot_signal_detector import BotSignalDetector


class Dummy:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


def test_suspicious_external_contact_bio_raises_risk():
    p = Dummy(bio="Пиши тільки в Telegram: @name", photo_urls="a,b", relationship_goal="relationship", age=25)
    res = ProfileRiskEvaluator.evaluate_profile_risk(p)
    assert res.risk_score >= 60
    assert "external_contact_in_bio" in res.flags


def test_obvious_scam_line_raises_scam_severity():
    p = Dummy(bio="", photo_urls="", relationship_goal="relationship", age=25)
    res = ScamSignalDetector.detect_scam_signals(p, ["Let's do crypto investment guaranteed profit asap, message me on telegram"])
    assert res.severity in {"medium", "high"}
    assert res.scam_risk >= 55


def test_repeated_generic_opener_increases_cringe_score():
    res = ConversationQualityEvaluator.evaluate_conversation_quality(["hi", "hi", "hi"])
    assert res["cringe_score"] >= 10
    assert "generic_lines" in res["flags"]


def test_message_harassment_gets_blocked():
    res = MessageRiskEvaluator.evaluate_message_risk("You are a slut", [], allow_edgy_mode=False)
    assert res.allowed is False
    assert "harassment" in res.flags


def test_recoverable_awkward_message_gets_rewrite_suggestion():
    res = MessageRiskEvaluator.evaluate_message_risk("you must be an angel my queen", [], allow_edgy_mode=False)
    assert res.risk_score >= 25
    assert res.rewrite_suggestion is not None


def test_bot_like_rapid_behavior_increases_probability():
    p = Dummy(bio="ok", photo_urls="", relationship_goal="relationship", age=25)
    res = BotSignalDetector.detect_bot_signals(
        p,
        {"swipes_last_minute": 90, "messages_last_minute": 20, "repeated_opener_ratio": 0.85, "identical_profile_template": True},
    )
    assert res.bot_probability >= 70
    assert "ultra_fast_swiping" in res.signals

