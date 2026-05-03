"""Add thread_id to ai_interaction_events for memory analytics."""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0038_ai_interaction_thread_id"
down_revision = "0037_profile_verification_v2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("ai_interaction_events") as batch:
        batch.add_column(sa.Column("thread_id", sa.String(length=64), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("ai_interaction_events") as batch:
        batch.drop_column("thread_id")
