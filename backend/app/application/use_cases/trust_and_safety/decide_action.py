from __future__ import annotations

from app.services.trust.action_policy import ActionPolicy, PolicyInput


def decide_safety_action(payload: dict) -> dict:
    inp = PolicyInput(
        message_risk=int(payload.get("message_risk", 0) or 0),
        profile_risk=int(payload.get("profile_risk", 0) or 0),
        bot_probability=int(payload.get("bot_probability", 0) or 0),
        scam_risk=int(payload.get("scam_risk", 0) or 0),
        conversation_quality=int(payload.get("conversation_quality", 70) or 70),
    )
    action, reasons = ActionPolicy().decide(inp)
    return {"action": action, "reasons": reasons}

