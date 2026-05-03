from __future__ import annotations

from datetime import date

from sqlalchemy import Date, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AiUsage(Base):
    __tablename__ = "ai_usage"
    __table_args__ = (UniqueConstraint("user_id", "date", name="uq_ai_usage_user_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    messages_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    openers_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    improves_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
