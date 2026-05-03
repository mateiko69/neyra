"""Mirror Paddle subscription fields on users (plan, status, expires_at).

Revision ID: 0039_user_subscription_paddle_mirror
Revises: 0038_ai_interaction_thread_id
Create Date: 2026-05-01
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0039_user_subscription_paddle_mirror"
down_revision = "0038_ai_interaction_thread_id"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("subscription_plan", sa.String(length=32), nullable=False, server_default="free"))
        batch.add_column(sa.Column("subscription_status", sa.String(length=32), nullable=False, server_default="inactive"))
        batch.add_column(sa.Column("subscription_expires_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.drop_column("subscription_expires_at")
        batch.drop_column("subscription_status")
        batch.drop_column("subscription_plan")
