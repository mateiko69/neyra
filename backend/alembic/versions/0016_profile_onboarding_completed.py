"""Add onboarding_completed flag to profiles.

Revision ID: 0016_profile_onboarding_completed
Revises: 0015_verification_attempt_limits
Create Date: 2026-04-24
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0016_profile_onboarding_completed"
down_revision = "0015_verification_attempt_limits"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Default false; existing users are evaluated by profile_needs_onboarding().
    op.add_column(
        "profiles",
        sa.Column("onboarding_completed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )


def downgrade() -> None:
    # Tolerant downgrade (won't crash if column already removed).
    try:
        op.drop_column("profiles", "onboarding_completed")
    except Exception:
        pass

