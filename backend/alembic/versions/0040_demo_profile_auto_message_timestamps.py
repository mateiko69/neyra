"""Add demo first/last auto message timestamps on profiles.

Revision ID: 0040_demo_profile_auto_message_timestamps
Revises: 0039_user_subscription_paddle_mirror
Create Date: 2026-05-01
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0040_demo_profile_auto_message_timestamps"
down_revision = "0039_user_subscription_paddle_mirror"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("profiles") as batch:
        batch.add_column(sa.Column("demo_first_message_sent_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("demo_last_auto_message_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("profiles") as batch:
        batch.drop_column("demo_last_auto_message_at")
        batch.drop_column("demo_first_message_sent_at")
