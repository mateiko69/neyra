from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StreakState:
    streak_count: int
    momentum_level: str

    def to_dict(self) -> dict:
        return {"streak_count": self.streak_count, "momentum_level": self.momentum_level}


class ConversationStreakTracker:
    """Tracks simple back-and-forth streak from an ordered message list.

    messages: list of {sender_id, receiver_id, ...} or tuples (sender_id, receiver_id).
    """

    @staticmethod
    def compute_streak(messages: list[dict], user_id: int) -> StreakState:
        # Count consecutive alternations in the last N messages.
        if not messages:
            return StreakState(0, "low")
        # Normalize to sender_id sequence
        senders = []
        for m in messages[-30:]:
            if isinstance(m, dict):
                senders.append(int(m.get("sender_id", 0)))
            else:
                senders.append(int(m[0]))

        streak = 1
        for i in range(len(senders) - 1, 0, -1):
            if senders[i] == senders[i - 1]:
                break
            streak += 1

        momentum = "low"
        if streak >= 8:
            momentum = "high"
        elif streak >= 4:
            momentum = "medium"
        return StreakState(streak_count=streak, momentum_level=momentum)

