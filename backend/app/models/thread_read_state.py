from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ThreadReadState(Base):
    __tablename__ = "thread_read_states"
    __table_args__ = (UniqueConstraint("user_id", "partner_user_id", name="uq_thread_read_pair"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    partner_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    last_read_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False)
