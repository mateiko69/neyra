from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.analytics_event import AnalyticsEvent
from app.services.analytics import track_event


class ReferralSystem:
    """Lightweight referral system using analytics events (no new tables yet)."""

    @staticmethod
    def generate_referral_code(user_id: int) -> str:
        seed = f"{user_id}:{settings.SECRET_KEY}".encode("utf-8")
        return hashlib.sha256(seed).hexdigest()[:10].upper()

    def get_referral_status(self, db: Session, user_id: int) -> dict:
        code = self.generate_referral_code(user_id)
        now = datetime.now(UTC)
        window = now - timedelta(days=365)
        rows = (
            db.query(AnalyticsEvent)
            .filter((AnalyticsEvent.name == "referral_joined") & (AnalyticsEvent.created_at >= window))
            .order_by(AnalyticsEvent.created_at.desc())
            .all()
        )
        invited_count = 0
        for r in rows:
            try:
                payload = json.loads(r.payload_json or "{}")
            except Exception:
                payload = {}
            if payload.get("referral_code") == code:
                invited_count += 1

        rewards = []
        if invited_count >= 3:
            rewards.append("visibility_boost")
        if invited_count >= 5:
            rewards.append("temporary_premium_24h")

        return {"referral_code": code, "invited_count": invited_count, "rewards_unlocked": rewards}

    def mark_referral_sent(self, db: Session, user_id: int) -> None:
        code = self.generate_referral_code(user_id)
        track_event(db, "referral_sent", user_id=user_id, payload={"referral_code": code})

