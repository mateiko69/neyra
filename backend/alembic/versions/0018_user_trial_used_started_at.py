"""Add is_trial_used and trial_started_at to users (conversion-optimized trial).

Revision ID: 0018_user_trial_used_started_at
Revises: 0017_user_premium_trial
Create Date: 2026-04-24
"""

from alembic import op
import sqlalchemy as sa


revision = "0018_user_trial_used_started_at"
down_revision = "0017_user_premium_trial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("is_trial_used", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("users", sa.Column("trial_started_at", sa.DateTime(timezone=True), nullable=True))

    # Backfill from legacy is_trial / premium_until if present.
    # - is_trial_used := is_trial
    # - trial_started_at := premium_until - 5 days (best-effort, only when premium_until is set)
    try:
        op.execute(sa.text("UPDATE users SET is_trial_used = TRUE WHERE COALESCE(is_trial, false) = TRUE"))
        op.execute(
            sa.text(
                "UPDATE users SET trial_started_at = (premium_until - interval '5 days') "
                "WHERE COALESCE(is_trial, false) = TRUE AND premium_until IS NOT NULL AND trial_started_at IS NULL"
            )
        )
    except Exception:
        # Backfill must never break migrations in partial schemas.
        pass


def downgrade() -> None:
    try:
        op.drop_column("users", "trial_started_at")
    except Exception:
        pass
    try:
        op.drop_column("users", "is_trial_used")
    except Exception:
        pass

