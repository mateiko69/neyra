from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.core.config import settings
from app.domain.viral.config import DEFAULT_VIRAL_CONFIG, ViralConfig
from app.models.analytics_event import AnalyticsEvent
from app.services.analytics import track_event
from app.services.growth.reward_system import RewardSystem


class ReferralEngine:
    """Strong referral engine using real tracking events (no fake installs).

    Tracking model (events):
    - referral_sent
    - referral_install (optional, from attribution)
    - referral_joined (registration)
    - referral_activated (activation milestone)
    """

    def __init__(self, config: ViralConfig = DEFAULT_VIRAL_CONFIG):
        self._c = config
        self._rewards = RewardSystem()

    @staticmethod
    def referral_code(user_id: int) -> str:
        seed = f"{user_id}:{settings.SECRET_KEY}".encode("utf-8")
        return hashlib.sha256(seed).hexdigest()[:10].upper()

    def generate_referral_link(self, db: Session, user_id: int) -> dict:
        code = self.referral_code(user_id)
        link = f"{self._c.referral_base_url}?code={code}"
        track_event(db, "invites_sent", user_id=user_id, payload={"referral_code": code})
        status = self._reward_status(db, user_id, code)
        return {"referral_link": link, "reward_status": status}

    def _reward_status(self, db: Session, user_id: int, code: str) -> dict:
        now = datetime.now(UTC)
        window = now - timedelta(days=365)
        rows = (
            db.query(AnalyticsEvent)
            .filter((AnalyticsEvent.created_at >= window) & (AnalyticsEvent.name.in_(["referral_install", "referral_joined", "referral_activated"])))
            .all()
        )

        installs = joins = activated = 0
        for r in rows:
            try:
                payload = json.loads(r.payload_json or "{}")
            except Exception:
                payload = {}
            if payload.get("referral_code") != code:
                continue
            if r.name == "referral_install":
                installs += 1
            elif r.name == "referral_joined":
                joins += 1
            elif r.name == "referral_activated":
                activated += 1

        rewards = []
        if activated >= 1:
            rewards.append("1_friend: 1 day premium")
        if activated >= 3:
            rewards.append("3_friends: AI unlimited 3 days")
        if activated >= 10:
            rewards.append("10_friends: profile boost")

        return {"installs": installs, "registrations": joins, "activated": activated, "rewards_unlocked": rewards}

