"""Add ai_trial_usage counters table.

Revision ID: 0013_ai_trial_usage
Revises: 0012_profile_verification_state_machine
Create Date: 2026-04-24
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.engine import Connection


# revision identifiers, used by Alembic.
revision = "0013_ai_trial_usage"
down_revision = "0012_profile_verification_state_machine"
branch_labels = None
depends_on = None


def _get_conn() -> Connection:
    conn = op.get_bind()
    if not isinstance(conn, Connection):
        # Alembic returns a Connection in normal online migrations; this keeps typing sane.
        raise TypeError("Expected SQLAlchemy Connection from op.get_bind()")
    return conn


def _pg_to_regclass_exists(name: str) -> bool:
    """
    PostgreSQL-safe existence check for tables/indexes via to_regclass().
    Works even if SQLAlchemy inspector caches stale metadata mid-migration.
    """
    conn = _get_conn()
    # Try unqualified and public-qualified names for robustness.
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


def _table_exists(table_name: str) -> bool:
    # Prefer PostgreSQL-native check; avoids schema/search_path surprises.
    return _pg_to_regclass_exists(table_name)


def _index_exists(index_name: str) -> bool:
    return _pg_to_regclass_exists(index_name)


def upgrade() -> None:
    # Idempotent/safe: the DB may already have the table or index (partially created).
    if not _table_exists("ai_trial_usage"):
        op.create_table(
            "ai_trial_usage",
            sa.Column("id", sa.Integer(), primary_key=True),
            # Do NOT set index=True here; we create the index explicitly below (conditionally).
            sa.Column(
                "user_id",
                sa.Integer(),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("trial_started_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.Column("ai_match_preview_used", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("ai_opener_used", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("ai_rewrite_used", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("ai_recovery_used", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("ai_escalation_used", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
            sa.UniqueConstraint("user_id", name="uq_ai_trial_usage_user_id"),
        )

    # Create the index only if missing (it may exist from a prior partial run).
    if not _index_exists("ix_ai_trial_usage_user_id"):
        op.create_index("ix_ai_trial_usage_user_id", "ai_trial_usage", ["user_id"])


def downgrade() -> None:
    # Make downgrade tolerant if objects are already missing.
    op.execute(sa.text('DROP INDEX IF EXISTS "ix_ai_trial_usage_user_id"'))
    op.execute(sa.text('DROP TABLE IF EXISTS "ai_trial_usage"'))

