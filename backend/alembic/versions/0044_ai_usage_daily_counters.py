"""Create ai_usage daily counters table (messages/openers/improves per UTC day).

The ORM model `AiUsage` uses this table; it was not created by earlier revisions.

Revision ID: 0044_ai_usage_daily_counters
Revises: 0043_subscription_paddle_webhook_occurred_at
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0044_ai_usage_daily_counters"
down_revision = "0043_subscription_paddle_webhook_occurred_at"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "ai_usage" in insp.get_table_names():
        return

    op.create_table(
        "ai_usage",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("messages_used", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("openers_used", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("improves_used", sa.Integer(), nullable=False, server_default="0"),
        sa.UniqueConstraint("user_id", "date", name="uq_ai_usage_user_date"),
    )
    op.create_index("ix_ai_usage_user_id", "ai_usage", ["user_id"])
    op.create_index("ix_ai_usage_date", "ai_usage", ["date"])


def downgrade() -> None:
    op.drop_index("ix_ai_usage_date", table_name="ai_usage")
    op.drop_index("ix_ai_usage_user_id", table_name="ai_usage")
    op.drop_table("ai_usage")
