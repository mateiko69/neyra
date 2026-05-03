"""Clamp profiles min/max preferred age to <= 80.

Revision ID: 0035_clamp_preferred_age_to_80
Revises: 0034_profile_height_and_job
Create Date: 2026-04-29
"""

from alembic import op


revision = "0035_clamp_preferred_age_to_80"
down_revision = "0034_profile_height_and_job"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Keep it simple and safe: clamp outliers created by earlier UI defaults (e.g. 99).
    op.execute("UPDATE profiles SET min_preferred_age = 80 WHERE min_preferred_age IS NOT NULL AND min_preferred_age > 80")
    op.execute("UPDATE profiles SET max_preferred_age = 80 WHERE max_preferred_age IS NOT NULL AND max_preferred_age > 80")
    # If min got clamped above max, fix max to match.
    op.execute(
        "UPDATE profiles SET max_preferred_age = min_preferred_age "
        "WHERE min_preferred_age IS NOT NULL AND max_preferred_age IS NOT NULL AND max_preferred_age < min_preferred_age"
    )


def downgrade() -> None:
    # No-op: data clamping is irreversible by definition.
    pass

