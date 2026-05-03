"""Add user_ai_memory and ai_interaction_events tables.

Revision ID: 0020_ai_memory_and_events
Revises: 0019_user_ai_profile
Create Date: 2026-04-24
"""

from alembic import op
import sqlalchemy as sa


revision = "0020_ai_memory_and_events"
down_revision = "0019_user_ai_profile"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_ai_memory",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("memory_type", sa.String(length=32), nullable=False),
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("value_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("confidence_score", sa.Float(), nullable=False, server_default=sa.text("0.5")),
        sa.Column("source", sa.String(length=64), nullable=False, server_default="system"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_user_ai_memory_user_id", "user_ai_memory", ["user_id"])
    op.create_index("ix_user_ai_memory_type_key", "user_ai_memory", ["user_id", "memory_type", "key"], unique=True)

    op.create_table(
        "ai_interaction_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("partner_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_ai_events_user_id", "ai_interaction_events", ["user_id"])
    op.create_index("ix_ai_events_partner_user_id", "ai_interaction_events", ["partner_user_id"])
    op.create_index("ix_ai_events_type", "ai_interaction_events", ["event_type"])


def downgrade() -> None:
    try:
        op.drop_index("ix_ai_events_type", table_name="ai_interaction_events")
        op.drop_index("ix_ai_events_partner_user_id", table_name="ai_interaction_events")
        op.drop_index("ix_ai_events_user_id", table_name="ai_interaction_events")
        op.drop_table("ai_interaction_events")
    except Exception:
        pass
    try:
        op.drop_index("ix_user_ai_memory_type_key", table_name="user_ai_memory")
        op.drop_index("ix_user_ai_memory_user_id", table_name="user_ai_memory")
        op.drop_table("user_ai_memory")
    except Exception:
        pass

