from app.services.ai.conversation.opener_generator import OpenerGenerator
from app.services.ai.conversation.reply_generator import ReplyGenerator
from app.services.ai.conversation.conversation_analyzer import ConversationAnalyzer
from app.services.ai.conversation.escalation_advisor import EscalationAdvisor


class Dummy:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


def test_no_generic_messages_in_openers():
    me = Dummy(interests="travel,music", bio="", display_name="Me")
    other = Dummy(interests="travel,books", bio="Люблю подорожі й нові міста. Запитай мене про найкращий трип?", display_name="Alex")
    openers = OpenerGenerator.generate_openers(me, other, allow_edgy_mode=False)
    assert 3 <= len(openers) <= 5
    banned = ("hi", "how are you", "як справи", "привіт, як")
    for o in openers:
        assert not any(b in o["text"].lower() for b in banned)


def test_different_styles_produce_different_outputs():
    me = Dummy(interests="music", bio="")
    other = Dummy(interests="music", bio="Люблю live-концерти.", display_name="N")
    openers = OpenerGenerator.generate_openers(me, other, allow_edgy_mode=False)
    texts = {o["text"] for o in openers}
    styles = {o["style"] for o in openers}
    assert len(texts) == len(openers)
    assert {"playful", "confident", "curious", "slightly_bold", "fallback_safe"} <= styles


def test_analyzer_returns_valid_ranges():
    analysis = ConversationAnalyzer.analyze_conversation(["Ок", "🙂", "А ти звідки?", "Клас!"])
    assert 0 <= analysis.interest_level <= 100
    assert 0 <= analysis.response_quality <= 100
    assert 0 <= analysis.risk_of_drop <= 100
    assert analysis.energy_level in {"low", "medium", "high"}


def test_escalation_suggestions_change_based_on_input():
    low = ConversationAnalyzer.analyze_conversation(["ок", "норм", "ага"])
    high = ConversationAnalyzer.analyze_conversation(["Хаха 🙂", "А ти завжди так багато подорожуєш?", "Кайф, розкажи ще!"])
    s_low = EscalationAdvisor.suggest_next_step(low)["suggestions"]
    s_high = EscalationAdvisor.suggest_next_step(high)["suggestions"]
    assert s_low != s_high


def test_reply_generator_returns_three_options():
    replies = ReplyGenerator.generate_replies("Ого, цікаво!", conversation_context=["Привіт", "Як день?"], user_style="chill", allow_edgy_mode=False)
    assert len(replies) == 3
    styles = [r["style"] for r in replies]
    assert styles == ["safe", "engaging", "slightly_bold"]

