from __future__ import annotations

from sqlalchemy.orm import Session

from app.services.analytics import track_event


class ShareToUnlock:
    """Optional share-to-unlock mechanics (never forced).

    This returns a suggestion; the UI can choose to surface it softly.
    """

    def propose(self, db: Session, user_id: int, context: dict) -> dict:
        ctype = (context.get("type") or "").strip()
        if ctype == "ai_suggestions":
            return {
                "show": True,
                "message": "Unlock 5 extra AI suggestions by inviting a friend (optional).",
                "reward": "ai_credits_5",
            }
        return {"show": False}

    def record_share(self, db: Session, user_id: int, payload: dict) -> None:
        track_event(db, "share", user_id=user_id, payload=payload)

