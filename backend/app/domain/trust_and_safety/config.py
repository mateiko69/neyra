from __future__ import annotations

from dataclasses import dataclass


SUSPICIOUS_BIO_PHRASES = {
    "telegram",
    "tg",
    "whatsapp",
    "insta",
    "instagram",
    "only telegram",
    "telegram only",
    "text me on",
    "write me on",
    "пиши в тг",
    "тільки телеграм",
    "в телеграм",
}

SCAM_PHRASES = {
    "crypto",
    "investment",
    "invest",
    "btc",
    "bitcoin",
    "usdt",
    "profit",
    "guaranteed",
    "forex",
    "sugar",
    "send money",
    "wire transfer",
    "gift card",
    "urgent",
    "asap",
    "need help",
    "lend",
    "loan",
    "pay my",
    "депозит",
    "інвестиції",
    "крипто",
}

HARASSMENT_PHRASES = {
    "slut",
    "whore",
    "idiot",
    "moron",
    "сука",
    "дурна",
    "дебіл",
}

EXPLICIT_PHRASES = {
    "nude",
    "nudes",
    "sex",
    "porn",
    "fuck",
    "секс",
    "нюд",
}

GENERIC_SPAM_OPENERS = {
    "hi",
    "hi there",
    "hello",
    "hey",
    "how are you",
    "привіт",
    "як справи",
    "привіт, як справи",
}

CRINGE_PHRASES = {
    "my queen",
    "goddess",
    "you must be an angel",
    "ти повинна",
    "ти маєш",
    "where are you from beautiful",
}


@dataclass(frozen=True)
class Thresholds:
    # Profile risk
    suspicious_profile_risk: int = 60
    require_review_profile_risk: int = 85

    # Message risk and actions
    hard_block_message_risk: int = 90
    soft_block_message_risk: int = 75
    warn_message_risk: int = 45
    rewrite_message_risk: int = 55

    # Bot/Scam
    possible_bot_probability: int = 70
    possible_scam_risk: int = 70

    # Downranking
    downrank_profile_risk: int = 50


DEFAULT_THRESHOLDS = Thresholds()

