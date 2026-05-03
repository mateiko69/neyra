"""Add user admin fields: created_at, last_active_at, is_banned.

Revision ID: 0022_user_admin_fields
Revises: 0021_profile_location_fields
Create Date: 2026-04-26
"""

from alembic import op
import sqlalchemy as sa


revision = "0022_user_admin_fields"
down_revision = "0021_profile_location_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # BOOLEAN defaults MUST use sa.text("false"/"true") for PostgreSQL compatibility.
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("created_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("last_active_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("is_banned", sa.Boolean(), server_default=sa.text("false"), nullable=False))


def downgrade() -> None:
    try:
        with op.batch_alter_table("users") as batch:
            batch.drop_column("is_banned")
            batch.drop_column("last_active_at")
            batch.drop_column("created_at")
    except Exception:
        pass

