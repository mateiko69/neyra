from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class UserAiProfile(Base):
    __tablename__ = "user_ai_profiles"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    preferred_style: Mapped[str] = mapped_column(String(16), default="light")  # light|flirty|deep

    # Behavior aggregates (no raw message storage).
    avg_message_length: Mapped[float] = mapped_column(Float, default=0.0)
    emoji_usage_level: Mapped[float] = mapped_column(Float, default=0.0)  # 0..1
    edit_rate: Mapped[float] = mapped_column(Float, default=0.0)  # 0..1

    # Simple counters for stable EWMA updates.
    samples: Mapped[int] = mapped_column(Integer, default=0)

    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))

