from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.analytics_event import AnalyticsEvent
from app.models.device_token import DeviceToken
from app.services.analytics import track_event
from app.services.monetization.paywalls import PaywallTrigger
from app.services.monetization.subscription_service import SubscriptionService
from app.services.push.service import get_push_provider


MonetizationEventType = Literal[
    "like_received",
    "match_created",
    "message_sent",
    "message_ignored",
    "chat_idle",
    "boost_used",
    "swipe_limit_reached",
]


UserSegment = Literal["explorer", "engager", "buyer", "idle"]


@dataclass(frozen=True)
class MonetizationAction:
    """Return value for the app client.

    - kind=none: do nothing
    - kind=paywall: show an in-app paywall / route to subscription
    - kind=push: backend already sent push; client may ignore
    """

    kind: Literal["none", "paywall", "push"]
    payload: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "payload": self.payload}


def _since(hours: int) -> datetime:
    return datetime.now(UTC) - timedelta(hours=hours)


def _count_events(db: Session, user_id: int, name: str, since: datetime) -> int:
    return int(
        db.query(func.count(AnalyticsEvent.id))
        .filter(
            AnalyticsEvent.user_id == user_id,
            AnalyticsEvent.name == name,
            AnalyticsEvent.created_at >= since,
        )
        .scalar()
        or 0
    )


def _segment(db: Session, user_id: int) -> UserSegment:
    subs = SubscriptionService()
    plan = subs.get_active_plan(db, user_id)
    if plan in {"premium", "premium_plus"}:
        return "buyer"
    day = datetime.now(UTC) - timedelta(days=1)
    week = datetime.now(UTC) - timedelta(days=7)
    sent = _count_events(db, user_id, "message_sent", week)
    swipes = _count_events(db, user_id, "swipe_created", day)
    active = _count_events(db, user_id, "app_opened", day) + _count_events(db, user_id, "page_viewed", day)
    if sent >= 3:
        return "engager"
    if active == 0 and swipes == 0 and sent == 0:
        return "idle"
    return "explorer"


def _push_locale(db: Session, user_id: int) -> str:
    # Best effort: profile.preferred_language exists; use it if present.
    try:
        from app.models.profile import Profile

        p = db.query(Profile).filter(Profile.user_id == user_id).first()
        code = str(getattr(p, "preferred_language", "") or "").strip().lower()
        return code or "en"
    except Exception:
        return "en"


def _push_copy(key: str, locale: str, vars: dict[str, Any] | None = None) -> tuple[str, str]:
    # Minimal on-server localized templates (en/uk/ru). Keep short.
    # NOTE: For full localization, migrate to message catalogs later.
    v = vars or {}
    l = (locale or "en").strip().lower()
    if l.startswith("uk"):
        rows = {
            "push.like_received": ("Новий лайк 👀", "Хтось зацікавився тобою."),
            "push.like_high_match": ("Сильний збіг ✨", "Лайк від користувача з високою сумісністю."),
            "push.chat_cold": ("AI має ідеальну відповідь для тебе", ""),
            "push.idle": ("Нові люди чекають", "Повернись у Discover — можуть бути хороші збіги."),
        }
    elif l.startswith("ru"):
        rows = {
            "push.like_received": ("Новый лайк 👀", "Кто-то заинтересовался тобой."),
            "push.like_high_match": ("Сильная совместимость ✨", "Лайк от человека с высокой совместимостью."),
            "push.chat_cold": ("AI подобрал идеальный ответ для тебя", ""),
            "push.idle": ("Новые люди ждут", "Загляни в Discover — могут быть хорошие совпадения."),
        }
    else:
        rows = {
            "push.like_received": ("New admirer 👀", "Someone liked you."),
            "push.like_high_match": ("Strong match ✨", "Someone with high compatibility liked you."),
            "push.chat_cold": ("AI has a perfect reply for you", ""),
            "push.idle": ("New people waiting", "Hop back into Discover."),
        }
    title, body = rows.get(key, ("NEYRA", "Open the app."))
    # simple formatting support
    for k, val in v.items():
        title = title.replace("{" + k + "}", str(val))
        body = body.replace("{" + k + "}", str(val))
    return title, body


class SmartMonetizationEngine:
    """Event-driven monetization orchestration.

    Responsibilities:
    - record normalized events
    - segment user
    - decide in-app paywall moments (non-aggressive)
    - send limited push notifications when meaningful
    - issue real expiring offers (timestamped)
    """

    MAX_PUSH_PER_DAY = 3

    def __init__(self):
        self._subs = SubscriptionService()
        self._paywalls = PaywallTrigger()

    def track_user_event(self, db: Session, user_id: int, event_type: MonetizationEventType, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        md = metadata if isinstance(metadata, dict) else {}
        # Always store the raw event in analytics.
        track_event(db, f"m_{event_type}", user_id=user_id, payload=md)

        segment = _segment(db, user_id)
        plan = self._subs.get_active_plan(db, user_id)

        # Decide action
        action = self._decide(db, user_id, event_type, md, segment, plan)
        return {"ok": True, "segment": segment, "plan": plan, "action": action.to_dict()}

    def _push_allowed(self, db: Session, user_id: int) -> bool:
        since = datetime.now(UTC) - timedelta(hours=24)
        sent = _count_events(db, user_id, "push_sent", since)
        return sent < self.MAX_PUSH_PER_DAY

    def _send_push(self, db: Session, user_id: int, key: str, vars: dict[str, Any] | None = None) -> bool:
        if not self._push_allowed(db, user_id):
            return False
        locale = _push_locale(db, user_id)
        title, body = _push_copy(key, locale, vars=vars)
        tokens = db.query(DeviceToken).filter(DeviceToken.user_id == user_id).all()
        if not tokens:
            return False
        provider = get_push_provider()
        ok_any = False
        for t in tokens[:6]:
            try:
                provider.send(str(t.token), title, body)
                ok_any = True
            except Exception:
                continue
        if ok_any:
            track_event(db, "push_sent", user_id=user_id, payload={"key": key, "locale": locale, "title": title, "body": body})
        return ok_any

    def _grant_offer(self, db: Session, user_id: int, offer_key: str, ttl_minutes: int, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        now = datetime.now(UTC)
        expires_at = now + timedelta(minutes=max(5, min(240, int(ttl_minutes))))
        pl = payload if isinstance(payload, dict) else {}
        pl2 = {**pl, "offer_key": offer_key, "expires_at": expires_at.isoformat()}
        track_event(db, "offer_granted", user_id=user_id, payload=pl2)
        return {"offer_key": offer_key, "expires_at": expires_at.isoformat()}

    def _active_offer(self, db: Session, user_id: int, offer_key: str) -> dict[str, Any] | None:
        # Scan recent grants only (fast enough with small volumes).
        since = datetime.now(UTC) - timedelta(days=2)
        rows = (
            db.query(AnalyticsEvent)
            .filter(AnalyticsEvent.user_id == user_id, AnalyticsEvent.name == "offer_granted", AnalyticsEvent.created_at >= since)
            .order_by(AnalyticsEvent.id.desc())
            .limit(20)
            .all()
        )
        for r in rows:
            try:
                pl = json.loads(r.payload_json or "{}")
            except Exception:
                pl = {}
            if str(pl.get("offer_key") or "") != offer_key:
                continue
            exp = str(pl.get("expires_at") or "").strip()
            if not exp:
                continue
            try:
                dt = datetime.fromisoformat(exp.replace("Z", "+00:00"))
            except Exception:
                continue
            if dt > datetime.now(UTC):
                return pl
        return None

    def _decide(
        self,
        db: Session,
        user_id: int,
        event_type: MonetizationEventType,
        md: dict[str, Any],
        segment: UserSegment,
        plan: str,
    ) -> MonetizationAction:
        is_free = plan == "free"
        if event_type == "like_received":
            # Push: only for meaningful events; never spam.
            high = bool(md.get("high_match")) or (isinstance(md.get("match_score"), (int, float)) and float(md.get("match_score")) >= 85)
            if high:
                self._send_push(db, user_id, "push.like_high_match")
            else:
                self._send_push(db, user_id, "push.like_received")
            # In-app: grant a real short offer to convert explorers.
            if is_free and segment in {"explorer", "idle"} and not self._active_offer(db, user_id, "entry_premium_2h"):
                offer = self._grant_offer(db, user_id, "entry_premium_2h", ttl_minutes=120, payload={"price_usd": "2.99"})
                return MonetizationAction("paywall", {"context": "likes_you", "offer": offer, "recommended_plan": "premium"})
            return MonetizationAction("none", {})

        if event_type in {"chat_idle", "message_ignored"}:
            # AI-driven moment: user needs help.
            if plan != "premium_plus":
                decision = self._paywalls.trigger_paywall(db, user_id, {"type": "reply_suggestion_request", "context": "reply_suggestion_request", "stage": "need"})
                if decision.get("show"):
                    track_event(db, "paywall_shown", user_id=user_id, payload={"context": "reply_suggestion_request"})
                    self._send_push(db, user_id, "push.chat_cold")
                    return MonetizationAction("paywall", {"context": "ai_replies", "decision": decision, "recommended_plan": "premium_plus"})
            return MonetizationAction("none", {})

        if event_type == "swipe_limit_reached":
            if is_free:
                if not self._active_offer(db, user_id, "entry_premium_swipes_2h"):
                    offer = self._grant_offer(db, user_id, "entry_premium_swipes_2h", ttl_minutes=120, payload={"price_usd": "2.99"})
                else:
                    offer = self._active_offer(db, user_id, "entry_premium_swipes_2h")
                track_event(db, "paywall_shown", user_id=user_id, payload={"context": "swipe_limit_reached"})
                return MonetizationAction("paywall", {"context": "swipe_limit_reached", "offer": offer, "recommended_plan": "premium"})
            return MonetizationAction("none", {})

        if event_type == "match_created":
            # Helpful opener moment: show Premium+ if engaged; Premium if explorer.
            if plan == "free":
                rec = "premium_plus" if segment == "engager" else "premium"
                decision = self._paywalls.trigger_paywall(db, user_id, {"type": "first_match", "context": "first_match", "stage": "moment"})
                if decision.get("show"):
                    track_event(db, "paywall_shown", user_id=user_id, payload={"context": "first_match"})
                    return MonetizationAction("paywall", {"context": "first_match", "decision": decision, "recommended_plan": rec})
            return MonetizationAction("none", {})

        if event_type == "boost_used":
            # Buyer loop: microtransaction upsell can live here later.
            return MonetizationAction("none", {})

        if event_type == "message_sent":
            return MonetizationAction("none", {})

        return MonetizationAction("none", {})

