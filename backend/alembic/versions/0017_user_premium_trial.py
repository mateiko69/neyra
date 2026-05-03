"""Add premium trial fields to users.

Revision ID: 0017_user_premium_trial
Revises: 0016_profile_onboarding_completed
Create Date: 2026-04-24
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0017_user_premium_trial"
down_revision = "0016_profile_onboarding_completed"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("premium_until", sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column("is_trial", sa.Boolean(), nullable=False, server_default=sa.text("false")))


def downgrade() -> None:
    # Tolerant downgrade.
    try:
        op.drop_column("users", "is_trial")
    except Exception:
        pass
    try:
        op.drop_column("users", "premium_until")
    except Exception:
        pass

