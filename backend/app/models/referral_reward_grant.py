from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ReferralRewardGrant(Base):
    """One row per inviter milestone (3 refs → 7d, 10 refs → 30d). Prevents duplicate premium grants."""

    __tablename__ = "referral_reward_grants"
    __table_args__ = (UniqueConstraint("user_id", "milestone_key", name="uq_referral_reward_user_milestone"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    milestone_key: Mapped[str] = mapped_column(String(16), nullable=False)
    premium_days: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
