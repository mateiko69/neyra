"""Align user safety tables with production schema.

Revision ID: 0010_user_safety_tables
Revises: 0009_user_safety_and_chat_features
Create Date: 2026-04-22
"""

from alembic import op
import sqlalchemy as sa


revision = "0010_user_safety_tables"
down_revision = "0009_user_safety_and_chat_features"
branch_labels = None
depends_on = None

REPORT_REASON_LENGTH = 255


def _has_table(table_name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(table_name)


def _get_columns(table_name: str) -> dict[str, dict]:
    return {
        column["name"]: column
        for column in sa.inspect(op.get_bind()).get_columns(table_name)
    }


def _has_column(table_name: str, column_name: str) -> bool:
    return column_name in _get_columns(table_name)


def _has_index(table_name: str, index_name: str) -> bool:
    return any(
        index["name"] == index_name
        for index in sa.inspect(op.get_bind()).get_indexes(table_name)
    )


def _has_unique_constraint(table_name: str, constraint_name: str) -> bool:
    return any(
        constraint["name"] == constraint_name
        for constraint in sa.inspect(op.get_bind()).get_unique_constraints(table_name)
    )


def _has_check_constraint(table_name: str, constraint_name: str) -> bool:
    return any(
        constraint["name"] == constraint_name
        for constraint in sa.inspect(op.get_bind()).get_check_constraints(table_name)
    )


def _get_string_length(table_name: str, column_name: str) -> int | None:
    column = _get_columns(table_name).get(column_name)
    if not column:
        return None
    return getattr(column.get("type"), "length", None)


def _create_index_if_missing(index_name: str, table_name: str, columns: list[str]) -> None:
    if _has_table(table_name) and not _has_index(table_name, index_name):
        op.create_index(index_name, table_name, columns)


def _create_unique_constraint_if_missing(
    constraint_name: str,
    table_name: str,
    columns: list[str],
) -> None:
    if _has_table(table_name) and not _has_unique_constraint(table_name, constraint_name):
        op.create_unique_constraint(constraint_name, table_name, columns)


def _create_not_self_check_if_missing(
    table_name: str,
    constraint_name: str,
    expression: str,
) -> None:
    if not _has_table(table_name) or _has_check_constraint(table_name, constraint_name):
        return

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            sa.text(
                f"ALTER TABLE {table_name} "
                f"ADD CONSTRAINT {constraint_name} CHECK ({expression}) NOT VALID"
            )
        )
        return

    op.create_check_constraint(constraint_name, table_name, expression)


def upgrade() -> None:
    if not _has_table("user_blocks"):
        op.create_table(
            "user_blocks",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("blocker_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("blocked_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("blocker_id", "blocked_id", name="uq_user_blocks_pair"),
            sa.CheckConstraint("blocker_id <> blocked_id", name="ck_user_blocks_not_self"),
        )
    _create_unique_constraint_if_missing(
        "uq_user_blocks_pair",
        "user_blocks",
        ["blocker_id", "blocked_id"],
    )
    _create_not_self_check_if_missing(
        "user_blocks",
        "ck_user_blocks_not_self",
        "blocker_id <> blocked_id",
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
            sa.CheckConstraint("user_id <> ignored_user_id", name="ck_user_ignores_not_self"),
        )
    _create_unique_constraint_if_missing(
        "uq_user_ignores_pair",
        "user_ignores",
        ["user_id", "ignored_user_id"],
    )
    _create_not_self_check_if_missing(
        "user_ignores",
        "ck_user_ignores_not_self",
        "user_id <> ignored_user_id",
    )
    _create_index_if_missing("ix_user_ignores_user_id", "user_ignores", ["user_id"])
    _create_index_if_missing("ix_user_ignores_ignored_user_id", "user_ignores", ["ignored_user_id"])

    if not _has_table("user_reports"):
        op.create_table(
            "user_reports",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("reporter_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("reported_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("reason", sa.String(length=REPORT_REASON_LENGTH), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
    else:
        if _has_column("user_reports", "category") and not _has_column("user_reports", "reason"):
            op.alter_column(
                "user_reports",
                "category",
                new_column_name="reason",
                existing_type=sa.String(length=32),
                existing_nullable=False,
            )
        elif not _has_column("user_reports", "reason"):
            op.add_column(
                "user_reports",
                sa.Column(
                    "reason",
                    sa.String(length=REPORT_REASON_LENGTH),
                    nullable=False,
                    server_default="other",
                ),
            )
            op.alter_column("user_reports", "reason", server_default=None)

        reason_length = _get_string_length("user_reports", "reason")
        if reason_length is not None and reason_length < REPORT_REASON_LENGTH:
            op.alter_column(
                "user_reports",
                "reason",
                existing_type=sa.String(length=reason_length),
                type_=sa.String(length=REPORT_REASON_LENGTH),
                existing_nullable=False,
            )

    _create_index_if_missing("ix_user_reports_reporter_id", "user_reports", ["reporter_id"])
    _create_index_if_missing("ix_user_reports_reported_user_id", "user_reports", ["reported_user_id"])


def downgrade() -> None:
    if _has_table("user_reports"):
        if not _has_column("user_reports", "details"):
            op.add_column(
                "user_reports",
                sa.Column("details", sa.Text(), nullable=False, server_default=""),
            )
        if _has_column("user_reports", "reason") and not _has_column("user_reports", "category"):
            reason_length = _get_string_length("user_reports", "reason") or REPORT_REASON_LENGTH
            op.alter_column(
                "user_reports",
                "reason",
                new_column_name="category",
                existing_type=sa.String(length=reason_length),
                existing_nullable=False,
            )

    if _has_table("user_ignores") and _has_check_constraint("user_ignores", "ck_user_ignores_not_self"):
        op.drop_constraint("ck_user_ignores_not_self", "user_ignores", type_="check")

    if _has_table("user_blocks") and _has_check_constraint("user_blocks", "ck_user_blocks_not_self"):
        op.drop_constraint("ck_user_blocks_not_self", "user_blocks", type_="check")
