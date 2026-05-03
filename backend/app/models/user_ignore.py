from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, validates

from app.db.base import Base


class UserIgnore(Base):
    __tablename__ = "user_ignores"
    __table_args__ = (
        UniqueConstraint("user_id", "ignored_user_id", name="uq_user_ignores_pair"),
        CheckConstraint("user_id <> ignored_user_id", name="ck_user_ignores_not_self"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    ignored_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))

    @validates("user_id", "ignored_user_id")
    def _validate_distinct_users(self, key: str, value: int) -> int:
        other_attr = "ignored_user_id" if key == "user_id" else "user_id"
        other_value = getattr(self, other_attr, None)
        if other_value is not None and other_value == value:
            raise ValueError("Users cannot ignore themselves")
        return value
