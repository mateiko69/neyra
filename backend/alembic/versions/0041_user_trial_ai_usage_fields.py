"""Ensure trial and free AI usage fields exist on users.

Revision ID: 0041_user_trial_ai_usage_fields
Revises: 0040_demo_profile_auto_message_timestamps
Create Date: 2026-05-01
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0041_user_trial_ai_usage_fields"
down_revision = "0040_demo_profile_auto_message_timestamps"
branch_labels = None
depends_on = None


def _column_names(table_name: str) -> set[str]:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    return {str(c.get("name") or "") for c in insp.get_columns(table_name)}


def upgrade() -> None:
    cols = _column_names("users")
    with op.batch_alter_table("users") as batch:
        if "trial_active" not in cols:
            batch.add_column(sa.Column("trial_active", sa.Boolean(), nullable=False, server_default=sa.text("false")))
        if "trial_expires_at" not in cols:
            batch.add_column(sa.Column("trial_expires_at", sa.DateTime(timezone=True), nullable=True))
        if "ai_free_used_count" not in cols:
            batch.add_column(sa.Column("ai_free_used_count", sa.Integer(), nullable=False, server_default=sa.text("0")))
        if "ai_last_used_at" not in cols:
            batch.add_column(sa.Column("ai_last_used_at", sa.DateTime(timezone=True), nullable=True))

    # Keep defaults only for backfill safety during migration; app-level defaults handle future inserts.
    with op.batch_alter_table("users") as batch:
        if "trial_active" not in cols:
            batch.alter_column("trial_active", server_default=None)
        if "ai_free_used_count" not in cols:
            batch.alter_column("ai_free_used_count", server_default=None)


def downgrade() -> None:
    cols = _column_names("users")
    with op.batch_alter_table("users") as batch:
        if "ai_last_used_at" in cols:
            batch.drop_column("ai_last_used_at")
        if "ai_free_used_count" in cols:
            batch.drop_column("ai_free_used_count")
        if "trial_expires_at" in cols:
            batch.drop_column("trial_expires_at")
        if "trial_active" in cols:
            batch.drop_column("trial_active")

