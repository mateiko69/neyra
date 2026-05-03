"""founder welcome and demo mode

Revision ID: 0025_founder_welcome_demo_mode
Revises: 0024_promo_codes
Create Date: 2026-04-26 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "0025_founder_welcome_demo_mode"
down_revision = "0024_promo_codes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("is_demo", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("profiles", sa.Column("founder_welcome_seen", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("profiles", sa.Column("is_demo_profile", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("profiles", sa.Column("demo_disclaimer", sa.Text(), nullable=False, server_default=""))
    op.add_column("messages", sa.Column("is_demo_simulation", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.create_table(
        "app_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(length=100), nullable=False),
        sa.Column("value_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("key"),
    )
    op.create_index(op.f("ix_app_settings_key"), "app_settings", ["key"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_app_settings_key"), table_name="app_settings")
    op.drop_table("app_settings")
    op.drop_column("messages", "is_demo_simulation")
    op.drop_column("profiles", "demo_disclaimer")
    op.drop_column("profiles", "is_demo_profile")
    op.drop_column("profiles", "founder_welcome_seen")
    op.drop_column("users", "is_demo")
