"""Persist subscription state to User + Subscription rows (Paddle-ready)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from app.models.subscription import Subscription
from app.models.user import User
from app.services.monetization.plan_entitlements import normalize_internal_plan


def apply_subscription_mirror(
    db: Session,
    *,
    user_id: int,
    internal_plan: str,
    status: str,
    expires_at: datetime | None,
    provider: str,
    provider_customer_id: str = "",
    provider_subscription_id: str = "",
    start_date: datetime | None = None,
    paddle_webhook_occurred_at: datetime | None = None,
) -> None:
    uid = int(user_id)
    plan_code = normalize_internal_plan(internal_plan)
    st = str(status or "inactive").strip().lower()

    user = db.query(User).filter(User.id == uid).first()
    if user:
        user.subscription_plan = plan_code if plan_code in {"premium", "premium_plus"} else "free"
        user.subscription_status = st
        user.subscription_expires_at = expires_at
        db.add(user)

    ps = str(provider_subscription_id or "").strip()
    row = None
    if ps:
        row = (
            db.query(Subscription)
            .filter(
                Subscription.user_id == uid,
                Subscription.provider_subscription_id == ps[:255],
            )
            .first()
        )
    if row is None:
        row = db.query(Subscription).filter(Subscription.user_id == uid).first()
    if not row:
        row = Subscription(user_id=uid)
        db.add(row)
    row.provider = str(provider or "paddle").strip() or "paddle"

    if plan_code not in {"premium", "premium_plus"}:
        row.status = "inactive"
        row.plan_code = "free"
        row.end_date = expires_at
        row.start_date = start_date or row.start_date
        if provider_customer_id:
            row.provider_customer_id = provider_customer_id[:255]
        if provider_subscription_id:
            row.provider_subscription_id = provider_subscription_id[:255]
        if paddle_webhook_occurred_at is not None:
            row.paddle_last_webhook_occurred_at = paddle_webhook_occurred_at
        db.commit()
        return

    row.plan_code = plan_code
    row.status = "active" if st == "active" else ("inactive" if st == "inactive" else st)
    if st == "past_due":
        row.status = "past_due"
    elif st == "canceled":
        row.status = "canceled"
    if provider_customer_id:
        row.provider_customer_id = provider_customer_id[:255]
    if provider_subscription_id:
        row.provider_subscription_id = provider_subscription_id[:255]
    row.start_date = start_date or row.start_date
    row.end_date = expires_at
    if paddle_webhook_occurred_at is not None:
        row.paddle_last_webhook_occurred_at = paddle_webhook_occurred_at
    db.commit()
