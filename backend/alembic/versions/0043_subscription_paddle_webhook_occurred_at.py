"""Subscription: store last Paddle webhook occurred_at for ordering.

Revision ID: 0043_subscription_paddle_webhook_occurred_at
Revises: 0042_paddle_webhook_events
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0043_subscription_paddle_webhook_occurred_at"
down_revision = "0042_paddle_webhook_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "subscriptions",
        sa.Column("paddle_last_webhook_occurred_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("subscriptions", "paddle_last_webhook_occurred_at")
