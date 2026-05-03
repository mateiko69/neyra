"""Paddle webhook idempotency table.

Revision ID: 0042_paddle_webhook_events
Revises: 0041_user_trial_ai_usage_fields
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0042_paddle_webhook_events"
down_revision = "0041_user_trial_ai_usage_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "paddle_webhook_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("event_id", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_id", name="uq_paddle_webhook_events_event_id"),
    )


def downgrade() -> None:
    op.drop_table("paddle_webhook_events")
