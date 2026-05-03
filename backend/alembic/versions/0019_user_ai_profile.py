"""Add user_ai_profiles table for AI learning.

Revision ID: 0019_user_ai_profile
Revises: 0018_user_trial_used_started_at
Create Date: 2026-04-24
"""

from alembic import op
import sqlalchemy as sa


revision = "0019_user_ai_profile"
down_revision = "0018_user_trial_used_started_at"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_ai_profiles",
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("preferred_style", sa.String(length=16), nullable=False, server_default="light"),
        sa.Column("avg_message_length", sa.Float(), nullable=False, server_default=sa.text("0")),
        sa.Column("emoji_usage_level", sa.Float(), nullable=False, server_default=sa.text("0")),
        sa.Column("edit_rate", sa.Float(), nullable=False, server_default=sa.text("0")),
        sa.Column("samples", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    try:
        op.drop_table("user_ai_profiles")
    except Exception:
        pass

