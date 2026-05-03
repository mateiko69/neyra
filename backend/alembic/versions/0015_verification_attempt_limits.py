"""Add verification attempt counter table.

Revision ID: 0015_verification_attempt_limits
Revises: 0014_user_soft_delete
Create Date: 2026-04-24
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.engine import Connection


# revision identifiers, used by Alembic.
revision = "0015_verification_attempt_limits"
down_revision = "0014_user_soft_delete"
branch_labels = None
depends_on = None


def _get_conn() -> Connection:
    conn = op.get_bind()
    if not isinstance(conn, Connection):
        raise TypeError("Expected SQLAlchemy Connection from op.get_bind()")
    return conn


def _pg_to_regclass_exists(name: str) -> bool:
    conn = _get_conn()
    return bool(
        conn.execute(
            text(
                """
                SELECT
                  to_regclass(:unqualified) IS NOT NULL
                  OR to_regclass(:public_qualified) IS NOT NULL
                """
            ),
            {"unqualified": name, "public_qualified": f"public.{name}"},
        ).scalar()
    )


def upgrade() -> None:
    # Idempotent/safe for fresh and partially-created databases.
    if not _pg_to_regclass_exists("verification_attempts"):
        op.create_table(
            "verification_attempts",
            sa.Column("id", sa.Integer(), primary_key=True),
            # Avoid index=True auto-creating indexes with the same names we create below.
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("day", sa.String(length=8), nullable=False),
            sa.Column("count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.UniqueConstraint("user_id", "day", name="uq_verification_attempts_user_day"),
        )

    if not _pg_to_regclass_exists("ix_verification_attempts_user_id"):
        op.create_index("ix_verification_attempts_user_id", "verification_attempts", ["user_id"])
    if not _pg_to_regclass_exists("ix_verification_attempts_day"):
        op.create_index("ix_verification_attempts_day", "verification_attempts", ["day"])


def downgrade() -> None:
    op.execute(sa.text('DROP INDEX IF EXISTS "ix_verification_attempts_day"'))
    op.execute(sa.text('DROP INDEX IF EXISTS "ix_verification_attempts_user_id"'))
    op.execute(sa.text('DROP TABLE IF EXISTS "verification_attempts"'))

