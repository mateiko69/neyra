"""Add status/category to user_reports.

Revision ID: 0023_user_reports_status_category
Revises: 0022_user_admin_fields
Create Date: 2026-04-26
"""

from alembic import op
import sqlalchemy as sa


revision = "0023_user_reports_status_category"
down_revision = "0022_user_admin_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("user_reports") as batch:
        batch.add_column(sa.Column("category", sa.String(length=32), nullable=False, server_default="other"))
        batch.add_column(sa.Column("status", sa.String(length=16), nullable=False, server_default="open"))


def downgrade() -> None:
    try:
        with op.batch_alter_table("user_reports") as batch:
            batch.drop_column("status")
            batch.drop_column("category")
    except Exception:
        pass

