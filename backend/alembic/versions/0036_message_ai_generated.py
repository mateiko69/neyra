"""Add messages.ai_generated flag.

Revision ID: 0036_message_ai_generated
Revises: 0035_clamp_preferred_age_to_80
Create Date: 2026-04-29
"""

from alembic import op
import sqlalchemy as sa


revision = "0036_message_ai_generated"
down_revision = "0035_clamp_preferred_age_to_80"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("messages") as batch:
        batch.add_column(
            sa.Column("ai_generated", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        )


def downgrade() -> None:
    try:
        with op.batch_alter_table("messages") as batch:
            batch.drop_column("ai_generated")
    except Exception:
        pass
