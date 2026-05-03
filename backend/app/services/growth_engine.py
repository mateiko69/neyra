from __future__ import annotations

import json
import logging
import random
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.domain.growth.config import DEFAULT_GROWTH_CONFIG, GrowthConfig
from app.models.analytics_event import AnalyticsEvent
from app.models.app_setting import AppSetting
from app.models.device_token import DeviceToken
from app.models.match import Match
from app.models.message import Message
from app.models.profile import Profile
from app.models.user import User
from app.services.analytics import track_event
from app.services.notifications import send_user_notification
from app.services.retention.notification_engine import NotificationEngine


ENGINE_SETTING_KEY = "growth_engine_state"

log = logging.getLogger("neyra.growth_engine")


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _aware_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


@dataclass(frozen=True)
class GrowthMetrics:
    onboarding_completion_rate: float
    first_message_rate: float
    reply_rate: float
    dead_chats_count: int
    matches_per_user: float

    def to_dict(self) -> dict:
        return {
            "onboarding_completion_rate": round(float(self.onboarding_completion_rate), 4),
            "first_message_rate": round(float(self.first_message_rate), 4),
            "reply_rate": round(float(self.reply_rate), 4),
            "dead_chats_count": int(self.dead_chats_count),
            "matches_per_user": round(float(self.matches_per_user), 4),
        }


@dataclass(frozen=True)
class GrowthAction:
    action_type: str
    enabled: bool
    reason: str
    payload: dict

    def to_dict(self) -> dict:
        return {
            "action_type": self.action_type,
            "enabled": bool(self.enabled),
            "reason": self.reason,
            "payload": self.payload,
        }


class GrowthEngine:
    """
    AI Growth Engine (safe mode):
    - Never auto-sends user messages.
    - Uses NotificationEngine anti-spam guard for pushes.
    - Writes state to AppSetting so behavior is inspectable and stable.
    """

    def __init__(self, config: GrowthConfig = DEFAULT_GROWTH_CONFIG):
        self._c = config
        self._notifications = NotificationEngine(config)

    # -----------------
    # Metrics
    # -----------------
    def read_metrics(self, db: Session) -> GrowthMetrics:
        now = _utcnow()
        window_7d = now - timedelta(days=7)
        window_24h = now - timedelta(hours=24)

        # Users: exclude demo/deleted/banned.
        users = db.query(User).filter(User.is_demo == False, User.is_deleted == False, User.is_banned == False).all()  # noqa: E712
        user_count = max(1, len(users))
        user_ids = [int(u.id) for u in users if u]

        # Onboarding completion rate (profile flag).
        onboarding_completed = (
            db.query(Profile)
            .filter(Profile.user_id.in_(user_ids), Profile.onboarding_completed == True)  # noqa: E712
            .count()
            if user_ids
            else 0
        )
        onboarding_rate = float(onboarding_completed) / float(user_count)

        # Matches per user (7d or all-time? use 7d to be responsive).
        matches_7d = (
            db.query(Match)
            .filter(and_(or_(Match.user_a_id.in_(user_ids), Match.user_b_id.in_(user_ids)), Match.created_at >= window_7d))
            .count()
            if user_ids
            else 0
        )
        matches_per_user = float(matches_7d) / float(user_count)

        # First message rate (24h): % of matches created in 24h that got at least one message.
        recent_matches = (
            db.query(Match)
            .filter(and_(or_(Match.user_a_id.in_(user_ids), Match.user_b_id.in_(user_ids)), Match.created_at >= window_24h))
            .all()
            if user_ids
            else []
        )
        first_message_hits = 0
        for m in recent_matches[:4000]:
            a = int(getattr(m, "user_a_id", 0) or 0)
            b = int(getattr(m, "user_b_id", 0) or 0)
            if not a or not b:
                continue
            has_any = (
                db.query(Message)
                .filter(
                    or_(
                        and_(Message.sender_id == a, Message.receiver_id == b),
                        and_(Message.sender_id == b, Message.receiver_id == a),
                    )
                )
                .count()
            )
            if int(has_any or 0) > 0:
                first_message_hits += 1
        first_message_rate = float(first_message_hits) / float(max(1, len(recent_matches)))

        # Reply rate (7d): received / sent for all users combined.
        sent_7d = db.query(Message).filter(and_(Message.sender_id.in_(user_ids), Message.created_at >= window_7d)).count() if user_ids else 0
        recv_7d = db.query(Message).filter(and_(Message.receiver_id.in_(user_ids), Message.created_at >= window_7d)).count() if user_ids else 0
        reply_rate = float(recv_7d) / float(max(1, sent_7d))

        # Dead chats count (24h silence after an incoming message with no outgoing after it).
        threshold = window_24h
        dead = 0
        for uid in user_ids[:2000]:
            last_in = (
                db.query(Message)
                .filter(Message.receiver_id == int(uid))
                .order_by(Message.created_at.desc())
                .first()
            )
            if not last_in or not getattr(last_in, "created_at", None):
                continue
            ts = _aware_utc(last_in.created_at)
            if ts > threshold:
                continue
            sent_after = db.query(Message).filter(and_(Message.sender_id == int(uid), Message.created_at > ts)).count()
            if int(sent_after or 0) == 0:
                dead += 1

        return GrowthMetrics(
            onboarding_completion_rate=onboarding_rate,
            first_message_rate=first_message_rate,
            reply_rate=reply_rate,
            dead_chats_count=int(dead),
            matches_per_user=matches_per_user,
        )

    # -----------------
    # State (AppSetting)
    # -----------------
    def _get_state(self, db: Session) -> dict:
        row = db.query(AppSetting).filter(AppSetting.key == ENGINE_SETTING_KEY).first()
        if not row or not getattr(row, "value_json", None):
            return {}
        try:
            val = json.loads(row.value_json)
        except Exception:
            return {}
        return val if isinstance(val, dict) else {}

    def _set_state(self, db: Session, state: dict) -> None:
        row = db.query(AppSetting).filter(AppSetting.key == ENGINE_SETTING_KEY).first()
        if not row:
            row = AppSetting(key=ENGINE_SETTING_KEY, value_json="{}")
        row.value_json = json.dumps(state)
        db.add(row)
        db.commit()

    # -----------------
    # Decisions
    # -----------------
    def decide_actions(self, metrics: GrowthMetrics) -> list[GrowthAction]:
        actions: list[GrowthAction] = []

        # Thresholds (MVP defaults; tune with data).
        onboarding_low = metrics.onboarding_completion_rate < 0.65
        first_message_low = metrics.first_message_rate < 0.45
        reply_rate_low = metrics.reply_rate < 0.70
        dead_chats_high = metrics.dead_chats_count >= 30

        if onboarding_low:
            actions.append(GrowthAction("enable_onboarding_nudges", True, "onboarding_low", {"rate": metrics.onboarding_completion_rate}))
        if first_message_low:
            actions.append(GrowthAction("push_opener_suggestions", True, "first_message_low", {"rate": metrics.first_message_rate}))
        if reply_rate_low:
            actions.append(GrowthAction("activate_revive_system", True, "reply_rate_low", {"reply_rate": metrics.reply_rate}))
        if dead_chats_high:
            actions.append(GrowthAction("send_revive_prompts", True, "dead_chats_high", {"dead_chats": metrics.dead_chats_count}))

        # Micro rewards are always allowed but limited; treat as optional action.
        actions.append(GrowthAction("micro_rewards", True, "always", {}))
        return actions

    # -----------------
    # Apply actions (safe mode)
    # -----------------
    def apply_actions(self, db: Session, actions: list[GrowthAction], metrics: GrowthMetrics) -> dict[str, int]:
        now = _utcnow()
        state = self._get_state(db)
        state.setdefault("last_run_at", None)
        state.setdefault("toggles", {})
        toggles = state["toggles"] if isinstance(state.get("toggles"), dict) else {}

        results = {"actions_applied": 0, "push_sent": 0, "push_suppressed": 0}

        def set_toggle(key: str, enabled: bool) -> None:
            toggles[key] = bool(enabled)

        # Persist toggles (for frontend experiments / admin visibility).
        for a in actions:
            if a.action_type == "enable_onboarding_nudges":
                set_toggle("onboarding_nudges", a.enabled)
                results["actions_applied"] += 1
            if a.action_type == "activate_revive_system":
                set_toggle("revive_system", a.enabled)
                results["actions_applied"] += 1

        # Push opener suggestions: target users with matches but no messages in last 24h.
        if any(a.action_type == "push_opener_suggestions" and a.enabled for a in actions):
            since = now - timedelta(hours=24)
            # only push to users with device tokens
            token_users = [int(r[0]) for r in db.query(DeviceToken.user_id).distinct().all() if r and r[0]]
            token_users = token_users[:2500]
            log.info(
                "growth_engine_push_opener_scan",
                extra={
                    "distinct_token_users": len(token_users),
                    "note": "push_sent stays 0 if NotificationEngine suppresses or no match/no-message eligibility",
                },
            )
            for uid in token_users:
                # quick eligibility: has match in 24h
                has_match = (
                    db.query(Match)
                    .filter(and_(or_(Match.user_a_id == uid, Match.user_b_id == uid), Match.created_at >= since))
                    .count()
                )
                if int(has_match or 0) == 0:
                    continue
                # no outgoing message in 24h
                sent = db.query(Message).filter(and_(Message.sender_id == uid, Message.created_at >= since)).count()
                if int(sent or 0) > 0:
                    continue
                decision = self._notifications.decide_notification(db, uid, {"type": "ai_hook"})
                if not decision.send or decision.channel != "push":
                    results["push_suppressed"] += 1
                    continue
                body = decision.body if (decision.body or "").strip() else " "
                send_user_notification(db, uid, decision.title, body)
                track_event(db, "notification_sent", user_id=uid, payload={"event": {"type": "ai_hook"}, "decision": decision.to_dict(), "source": "growth_engine"})
                results["push_sent"] += 1

        # Revive prompts: target dead chats (reuse notification type so cooldown applies).
        if any(a.action_type == "send_revive_prompts" and a.enabled for a in actions):
            threshold = now - timedelta(hours=24)
            token_users = [int(r[0]) for r in db.query(DeviceToken.user_id).distinct().all() if r and r[0]][:2500]
            log.info("growth_engine_revive_scan", extra={"distinct_token_users": len(token_users)})
            for uid in token_users:
                last_in = (
                    db.query(Message)
                    .filter(Message.receiver_id == int(uid))
                    .order_by(Message.created_at.desc())
                    .first()
                )
                if not last_in or not getattr(last_in, "created_at", None):
                    continue
                ts = _aware_utc(last_in.created_at)
                if ts > threshold:
                    continue
                sent_after = db.query(Message).filter(and_(Message.sender_id == int(uid), Message.created_at > ts)).count()
                if int(sent_after or 0) != 0:
                    continue
                decision = self._notifications.decide_notification(db, uid, {"type": "dead_chat_revive"})
                if not decision.send or decision.channel != "push":
                    results["push_suppressed"] += 1
                    continue
                body = decision.body if (decision.body or "").strip() else " "
                send_user_notification(db, uid, decision.title, body)
                track_event(db, "notification_sent", user_id=uid, payload={"event": {"type": "dead_chat_revive"}, "decision": decision.to_dict(), "source": "growth_engine"})
                results["push_sent"] += 1

        # Micro rewards (low priority, randomized, gated by NotificationEngine).
        if any(a.action_type == "micro_rewards" and a.enabled for a in actions):
            since = now - timedelta(hours=24)
            token_users = [int(r[0]) for r in db.query(DeviceToken.user_id).distinct().all() if r and r[0]][:2500]
            for uid in token_users:
                if random.random() > 0.05:
                    continue
                views = (
                    db.query(AnalyticsEvent)
                    .filter(and_(AnalyticsEvent.user_id == uid, AnalyticsEvent.name == "profile_viewed", AnalyticsEvent.created_at >= since))
                    .count()
                )
                matches = (
                    db.query(Match)
                    .filter(and_(or_(Match.user_a_id == uid, Match.user_b_id == uid), Match.created_at >= since))
                    .count()
                )
                if int(views or 0) < 2 and int(matches or 0) < 1:
                    continue
                t = "micro_reward_trending" if int(views or 0) >= 6 or int(matches or 0) >= 3 else "micro_reward_noticed"
                decision = self._notifications.decide_notification(db, uid, {"type": t})
                if not decision.send or decision.channel != "push":
                    results["push_suppressed"] += 1
                    continue
                body = decision.body if (decision.body or "").strip() else " "
                send_user_notification(db, uid, decision.title, body)
                track_event(db, "notification_sent", user_id=uid, payload={"event": {"type": t}, "decision": decision.to_dict(), "source": "growth_engine"})
                results["push_sent"] += 1

        state["toggles"] = toggles
        state["last_run_at"] = now.isoformat()
        state["last_metrics"] = metrics.to_dict()
        self._set_state(db, state)
        return results

    # -----------------
    # Full loop
    # -----------------
    def run_once(self, db: Session) -> dict:
        metrics = self.read_metrics(db)
        actions = self.decide_actions(metrics)
        track_event(db, "growth_engine_metrics", user_id=None, payload=metrics.to_dict())
        for a in actions:
            track_event(db, "growth_engine_action", user_id=None, payload=a.to_dict())
        applied = self.apply_actions(db, actions, metrics)
        track_event(db, "growth_engine_applied", user_id=None, payload={"applied": applied, "metrics": metrics.to_dict()})
        return {"metrics": metrics.to_dict(), "actions": [a.to_dict() for a in actions], "applied": applied}

