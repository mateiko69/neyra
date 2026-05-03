from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.models.swipe import Swipe
from app.models.match import Match


class SocialProofEngine:
    """Generates real, aggregated social proof signals (no fake metrics)."""

    def get_signals(self, db: Session, user_id: int) -> list[dict]:
        now = datetime.now(UTC)
        since = now - timedelta(days=1)

        likes_today = (
            db.query(Swipe)
            .filter((Swipe.target_user_id == user_id) & (Swipe.liked == True) & (Swipe.created_at >= since))  # noqa: E712
            .count()
        )
        matches_today = (
            db.query(Match)
            .filter(((Match.user_a_id == user_id) | (Match.user_b_id == user_id)) & (Match.created_at >= since))
            .count()
        )

        out: list[dict] = []
        if likes_today >= 1:
            out.append({"text": f"{likes_today} people liked you today", "type": "likes_today"})
        if matches_today >= 1:
            out.append({"text": f"You got {matches_today} new matches today", "type": "matches_today"})

        # Keep “trending” only if based on real counts.
        if likes_today >= 5:
            out.append({"text": "You’re trending today ✨", "type": "trending"})

        return out[:4]

