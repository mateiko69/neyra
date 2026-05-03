"""Add voice message attachment fields.

Revision ID: 0011_voice_messages
Revises: 0010_user_safety_tables
Create Date: 2026-04-23
"""

from alembic import op
import sqlalchemy as sa


revision = "0011_voice_messages"
down_revision = "0010_user_safety_tables"
branch_labels = None
depends_on = None


def _has_table(table_name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table_name)


def _has_column(table_name: str, column_name: str) -> bool:
    return any(
        column["name"] == column_name
        for column in sa.inspect(op.get_bind()).get_columns(table_name)
    )


def _create_index_if_missing(index_name: str, table_name: str, columns: list[str]) -> None:
    if not _has_table(table_name):
        return
    if any(
        index["name"] == index_name
        for index in sa.inspect(op.get_bind()).get_indexes(table_name)
    ):
        return
    op.create_index(index_name, table_name, columns)


def upgrade() -> None:
    if _has_table("messages") and not _has_column("messages", "voice_url"):
        op.add_column("messages", sa.Column("voice_url", sa.Text(), nullable=True))
    if _has_table("messages") and not _has_column("messages", "voice_mime"):
        op.add_column("messages", sa.Column("voice_mime", sa.String(length=80), nullable=True))
    if _has_table("messages") and not _has_column("messages", "voice_duration_ms"):
        op.add_column("messages", sa.Column("voice_duration_ms", sa.Integer(), nullable=True))

    _create_index_if_missing("ix_messages_voice_url", "messages", ["voice_url"])


def downgrade() -> None:
    if _has_table("messages") and _has_column("messages", "voice_duration_ms"):
        op.drop_column("messages", "voice_duration_ms")
    if _has_table("messages") and _has_column("messages", "voice_mime"):
        op.drop_column("messages", "voice_mime")
    if _has_table("messages") and _has_column("messages", "voice_url"):
        op.drop_column("messages", "voice_url")
