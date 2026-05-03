from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, validates

from app.db.base import Base


class IncomingLikeHide(Base):
    """Viewer chose to hide an admirer from the incoming-likes list (UI-only; does not affect matches/chat)."""

    __tablename__ = "incoming_like_hides"
    __table_args__ = (
        UniqueConstraint("viewer_user_id", "admirer_user_id", name="uq_incoming_like_hides_pair"),
        CheckConstraint("viewer_user_id <> admirer_user_id", name="ck_incoming_like_hides_not_self"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    viewer_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    admirer_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))

    @validates("viewer_user_id", "admirer_user_id")
    def _validate_distinct_users(self, key: str, value: int) -> int:
        other_attr = "admirer_user_id" if key == "viewer_user_id" else "viewer_user_id"
        other_value = getattr(self, other_attr, None)
        if other_value is not None and other_value == value:
            raise ValueError("Cannot hide self as incoming like")
        return value
