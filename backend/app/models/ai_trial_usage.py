from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AiTrialUsage(Base):
    """
    Durable counters for the new-user AI trial.

    We keep this minimal and append-only in spirit:
    - one row per user
    - counters increment as features are used
    - trial_started_at anchors the 3-day window (if we choose to anchor to first use)
    """

    __tablename__ = "ai_trial_usage"
    __table_args__ = (
        UniqueConstraint("user_id", name="uq_ai_trial_usage_user_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)

    trial_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Optional: when we last incremented (debug/support).
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Counters
    ai_match_preview_used: Mapped[int] = mapped_column(Integer, default=0)
    ai_opener_used: Mapped[int] = mapped_column(Integer, default=0)
    ai_rewrite_used: Mapped[int] = mapped_column(Integer, default=0)
    ai_recovery_used: Mapped[int] = mapped_column(Integer, default=0)
    ai_escalation_used: Mapped[int] = mapped_column(Integer, default=0)

    # Marker/support field if we need to hard-disable trial for an account.
    status: Mapped[str] = mapped_column(String(32), default="active")

