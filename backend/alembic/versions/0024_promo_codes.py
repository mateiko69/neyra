"""Add promo_codes table.

Revision ID: 0024_promo_codes
Revises: 0023_user_reports_status_category
Create Date: 2026-04-26
"""

from alembic import op
import sqlalchemy as sa


revision = "0024_promo_codes"
down_revision = "0023_user_reports_status_category"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "promo_codes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("days", sa.Integer(), nullable=False, server_default=sa.text("7")),
        sa.Column("max_uses", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("uses_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        # BOOLEAN defaults MUST use sa.text("false"/"true") for PostgreSQL compatibility.
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("code", name="uq_promo_code"),
    )
    op.create_index("ix_promo_codes_code", "promo_codes", ["code"])


def downgrade() -> None:
    try:
        op.drop_index("ix_promo_codes_code", table_name="promo_codes")
    except Exception:
        pass
    try:
        op.drop_table("promo_codes")
    except Exception:
        pass

