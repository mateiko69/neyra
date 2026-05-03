from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Subscription(Base):
    __tablename__ = "subscriptions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    provider: Mapped[str] = mapped_column(String(50), default="mock")
    provider_customer_id: Mapped[str] = mapped_column(String(255), default="")
    provider_subscription_id: Mapped[str] = mapped_column(String(255), default="")
    status: Mapped[str] = mapped_column(String(50), default="inactive")
    plan_code: Mapped[str] = mapped_column(String(50), default="free")
    start_date: Mapped[datetime | None] = mapped_column(nullable=True)
    end_date: Mapped[datetime | None] = mapped_column(nullable=True)
    # Latest Paddle notification time applied for ordering (ignore stale webhooks).
    paddle_last_webhook_occurred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
