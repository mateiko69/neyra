"""Add profiles.preferred_gender for discover deck filtering.

Revision ID: 0029_profile_preferred_gender
Revises: 0028_demo_behavior_profile_fields
"""

from alembic import op
import sqlalchemy as sa


revision = "0029_profile_preferred_gender"
down_revision = "0028_demo_behavior_profile_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("profiles") as batch:
        batch.add_column(sa.Column("preferred_gender", sa.String(length=32), nullable=False, server_default=""))


def downgrade() -> None:
    try:
        with op.batch_alter_table("profiles") as batch:
            batch.drop_column("preferred_gender")
    except Exception:
        pass
