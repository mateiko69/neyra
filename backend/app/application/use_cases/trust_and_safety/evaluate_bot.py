from __future__ import annotations

from app.services.trust.bot_signal_detector import BotSignalDetector


def detect_bot_signals(profile, behavior_data: dict | None) -> dict:
    return BotSignalDetector.detect_bot_signals(profile, behavior_data).to_dict()

