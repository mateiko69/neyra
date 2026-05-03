"""Add user safety and chat features (block/ignore/report/reactions/reply).

Revision ID: 0009_user_safety_and_chat_features
Revises: 0008_profile_language
Create Date: 2026-04-22
"""

from alembic import op
import sqlalchemy as sa


revision = "0009_user_safety_and_chat_features"
down_revision = "0008_profile_language"
branch_labels = None
depends_on = None


def _has_table(table_name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table_name)


def _has_column(table_name: str, column_name: str) -> bool:
    return any(
        column["name"] == column_name
        for column in sa.inspect(op.get_bind()).get_columns(table_name)
    )


def _has_index(table_name: str, index_name: str) -> bool:
    return any(
        index["name"] == index_name
        for index in sa.inspect(op.get_bind()).get_indexes(table_name)
    )


def _create_index_if_missing(index_name: str, table_name: str, columns: list[str]) -> None:
    if _has_table(table_name) and not _has_index(table_name, index_name):
        op.create_index(index_name, table_name, columns)


def upgrade() -> None:
    if not _has_table("user_blocks"):
        op.create_table(
            "user_blocks",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("blocker_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("blocked_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("blocker_id", "blocked_id", name="uq_user_blocks_pair"),
        )
    _create_index_if_missing("ix_user_blocks_blocker_id", "user_blocks", ["blocker_id"])
    _create_index_if_missing("ix_user_blocks_blocked_id", "user_blocks", ["blocked_id"])

    if not _has_table("user_ignores"):
        op.create_table(
            "user_ignores",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("ignored_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("user_id", "ignored_user_id", name="uq_user_ignores_pair"),
        )
    _create_index_if_missing("ix_user_ignores_user_id", "user_ignores", ["user_id"])
    _create_index_if_missing("ix_user_ignores_ignored_user_id", "user_ignores", ["ignored_user_id"])

    if not _has_table("user_reports"):
        op.create_table(
            "user_reports",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("reporter_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("reported_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("category", sa.String(length=32), nullable=False),
            sa.Column("details", sa.Text(), nullable=False, server_default=""),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
    _create_index_if_missing("ix_user_reports_reporter_id", "user_reports", ["reporter_id"])
    _create_index_if_missing("ix_user_reports_reported_user_id", "user_reports", ["reported_user_id"])

    if not _has_table("message_reactions"):
        op.create_table(
            "message_reactions",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("message_id", sa.Integer(), sa.ForeignKey("messages.id"), nullable=False),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("emoji", sa.String(length=8), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("message_id", "user_id", "emoji", name="uq_message_reactions_unique"),
        )
    _create_index_if_missing("ix_message_reactions_message_id", "message_reactions", ["message_id"])
    _create_index_if_missing("ix_message_reactions_user_id", "message_reactions", ["user_id"])

    if not _has_column("messages", "reply_to_message_id"):
        op.add_column(
            "messages",
            sa.Column("reply_to_message_id", sa.Integer(), sa.ForeignKey("messages.id"), nullable=True),
        )
    _create_index_if_missing("ix_messages_reply_to_message_id", "messages", ["reply_to_message_id"])


def downgrade() -> None:
    op.drop_index("ix_messages_reply_to_message_id", table_name="messages")
    op.drop_column("messages", "reply_to_message_id")

    op.drop_index("ix_message_reactions_user_id", table_name="message_reactions")
    op.drop_index("ix_message_reactions_message_id", table_name="message_reactions")
    op.drop_table("message_reactions")

    op.drop_index("ix_user_reports_reported_user_id", table_name="user_reports")
    op.drop_index("ix_user_reports_reporter_id", table_name="user_reports")
    op.drop_table("user_reports")

    op.drop_index("ix_user_ignores_ignored_user_id", table_name="user_ignores")
    op.drop_index("ix_user_ignores_user_id", table_name="user_ignores")
    op.drop_table("user_ignores")

    op.drop_index("ix_user_blocks_blocked_id", table_name="user_blocks")
    op.drop_index("ix_user_blocks_blocker_id", table_name="user_blocks")
    op.drop_table("user_blocks")
