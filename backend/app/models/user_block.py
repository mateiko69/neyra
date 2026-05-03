from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, validates

from app.db.base import Base


class UserBlock(Base):
    __tablename__ = "user_blocks"
    __table_args__ = (
        UniqueConstraint("blocker_id", "blocked_id", name="uq_user_blocks_pair"),
        CheckConstraint("blocker_id <> blocked_id", name="ck_user_blocks_not_self"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    blocker_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    blocked_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))

    @validates("blocker_id", "blocked_id")
    def _validate_distinct_users(self, key: str, value: int) -> int:
        other_attr = "blocked_id" if key == "blocker_id" else "blocker_id"
        other_value = getattr(self, other_attr, None)
        if other_value is not None and other_value == value:
            raise ValueError("Users cannot block themselves")
        return value
