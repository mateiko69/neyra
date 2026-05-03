from __future__ import annotations

from app.services.fraud.scam_signal_detector import ScamSignalDetector


def detect_scam_signals(profile, messages: list[str] | None) -> dict:
    return ScamSignalDetector.detect_scam_signals(profile, messages).to_dict()

