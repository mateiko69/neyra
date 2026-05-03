"""Legacy premium engine (kept for backward compatibility).

Monetization now lives in `app/services/monetization/*` with plan-aware gating.
"""

from sqlalchemy.orm import Session

from app.services.monetization.access import MonetizationAccess


class PremiumEngine:
    def check_feature_access(self, db: Session, user_id: int, feature: str) -> dict:
        # Map old feature names to new ones.
        mapping = {
            "unlimited_ai_suggestions": "ai_unlimited_replies",
            "advanced_compatibility_insights": "advanced_match_insights",
            "conversation_coach_insights": "ai_conversation_analysis",
            "priority_ranking": "profile_boost",
            "see_who_liked_you": "see_who_liked_you",
        }
        f = mapping.get((feature or "").strip(), feature)
        try:
            return MonetizationAccess().check_access(db, user_id, f)  # type: ignore[arg-type]
        except Exception:
            return {"allowed": True}

