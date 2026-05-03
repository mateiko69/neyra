from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.domain.growth.config import DEFAULT_GROWTH_CONFIG, GrowthConfig
from app.models.analytics_event import AnalyticsEvent


# Product copy: short, emotional hooks (title is what users see first on most OSes).
SMART_PUSH_COPY: dict[str, tuple[str, str]] = {
    "new_match": ("You've got a new match 😏", ""),
    "new_message": ("They replied — don't leave them waiting", ""),
    "streak_reminder": ("You're on fire 🔥 come back", ""),
    "ai_hook": ("AI has a perfect reply for you", ""),
    "dead_chat_revive": ("This chat can still work 👀", ""),
}


def _copy_for(event_type: str, *, extra_body: str | None = None) -> tuple[str, str]:
    title, body = SMART_PUSH_COPY.get(event_type, ("NEYRA", ""))
    if not title:
        title = "NEYRA"
    if extra_body:
        body = extra_body.strip()
    return title, body


_TRANSACTIONAL = frozenset({"new_message", "new_match"})


def _count_transactional_notifications(db: Session, user_id: int, since: datetime) -> int:
    rows = (
        db.query(AnalyticsEvent.payload_json)
        .filter(
            AnalyticsEvent.user_id == user_id,
            AnalyticsEvent.name == "notification_sent",
            AnalyticsEvent.created_at >= since,
        )
        .all()
    )
    n = 0
    for (pj,) in rows:
        try:
            data = json.loads(pj or "{}")
            ev = data.get("event")
            if isinstance(ev, dict) and str(ev.get("type") or "").strip() in _TRANSACTIONAL:
                n += 1
        except Exception:
            continue
    return n


@dataclass(frozen=True)
class NotificationDecision:
    send: bool
    channel: str
    title: str
    body: str
    priority: str

    @property
    def message(self) -> str:
        """Backward compat for callers expecting a single text field."""
        if self.body:
            return f"{self.title} {self.body}".strip()
        return self.title

    def to_dict(self) -> dict:
        return {
            "send": self.send,
            "channel": self.channel,
            "title": self.title,
            "body": self.body,
            "message": self.message,
            "priority": self.priority,
        }


# Nudges that must not stack too tightly (transactional excluded).
_COOLDOWN_TYPES = frozenset(
    {
        "inactive_user",
        "premium_offer",
        "daily_new_matches",
        "daily_profile_views",
        "dead_chat_revive",
        "micro_reward_noticed",
        "micro_reward_trending",
        "streak_reminder",
        "ai_hook",
    }
)


class NotificationEngine:
    """Decides notification delivery with strict anti-spam limits."""

    def __init__(self, config: GrowthConfig = DEFAULT_GROWTH_CONFIG):
        self._c = config

    def decide_notification(self, db: Session, user_id: int, event: dict) -> NotificationDecision:
        event_type = (event.get("type") or "").strip()
        if not event_type:
            return NotificationDecision(False, "in_app", "", "", "low")

        now = datetime.now(UTC)
        day_ago = now - timedelta(days=1)

        push_sent_total = (
            db.query(AnalyticsEvent)
            .filter((AnalyticsEvent.user_id == user_id) & (AnalyticsEvent.name == "notification_sent") & (AnalyticsEvent.created_at >= day_ago))
            .count()
        )

        if event_type in _TRANSACTIONAL:
            if _count_transactional_notifications(db, user_id, day_ago) >= self._c.max_transactional_push_per_day:
                return NotificationDecision(False, "in_app", "", "", "low")
        elif push_sent_total >= self._c.max_push_per_day:
            return NotificationDecision(False, "in_app", "", "", "low")

        cooldown = now - timedelta(minutes=self._c.push_cooldown_minutes)
        recent = (
            db.query(AnalyticsEvent)
            .filter((AnalyticsEvent.user_id == user_id) & (AnalyticsEvent.name == "notification_sent") & (AnalyticsEvent.created_at >= cooldown))
            .count()
        )
        if recent >= 1 and event_type in _COOLDOWN_TYPES:
            return NotificationDecision(False, "in_app", "", "", "low")

        if event_type == "new_message":
            t, b = _copy_for("new_message")
            return NotificationDecision(True, "push", t, b, "high")

        if event_type == "new_match":
            t, b = _copy_for("new_match")
            return NotificationDecision(True, "push", t, b, "high")

        if event_type == "streak_reminder":
            t, b = _copy_for("streak_reminder")
            return NotificationDecision(True, "push", t, b, "medium")

        if event_type == "ai_hook":
            t, b = _copy_for("ai_hook")
            return NotificationDecision(True, "push", t, b, "medium")

        if event_type == "inactive_user":
            t, b = _copy_for("ai_hook")
            return NotificationDecision(True, "push", t, b, "medium")

        if event_type == "daily_new_matches":
            n = int(event.get("count") or 0)
            extra = f"{n} new match{'es' if n != 1 else ''} waiting." if n > 1 else "Someone is waiting for you."
            t, _ = _copy_for("new_match")
            return NotificationDecision(True, "push", t, extra, "high")

        if event_type == "daily_profile_views":
            return NotificationDecision(
                True,
                "in_app",
                "Profile views",
                "A quick refresh can turn views into matches.",
                "medium",
            )

        if event_type == "dead_chat_revive":
            t, b = _copy_for("dead_chat_revive")
            return NotificationDecision(True, "push", t, b, "high")

        if event_type == "micro_reward_noticed":
            return NotificationDecision(True, "in_app", "You're getting noticed", "Open NEYRA to keep the momentum.", "low")

        if event_type == "micro_reward_trending":
            return NotificationDecision(True, "in_app", "Profile momentum", "Small updates can boost your visibility.", "low")

        if event_type == "profile_boost":
            return NotificationDecision(True, "in_app", "Your profile is getting attention", "A fresh photo can boost it further.", "medium")

        if event_type == "premium_offer":
            return NotificationDecision(True, "in_app", "Stronger AI help", "Premium unlocks deeper suggestions when you're ready.", "medium")

        return NotificationDecision(False, "in_app", "", "", "low")
