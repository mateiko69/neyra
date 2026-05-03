"""thread read states and matches seen timestamp

Idempotent guards: some environments may have partially-created tables.
This migration must not fail with "relation already exists".
"""

revision = "0004_nav_badges"
down_revision = "0003_subscription_periods"
branch_labels = None
depends_on = None

import sqlalchemy as sa
from alembic import op


def upgrade():
    insp = sa.inspect(op.get_bind())

    user_cols = {c["name"] for c in insp.get_columns("users")}
    if "matches_last_seen_at" not in user_cols:
        op.add_column("users", sa.Column("matches_last_seen_at", sa.DateTime(), nullable=True))
        op.execute(
            sa.text(
                "UPDATE users SET matches_last_seen_at = CURRENT_TIMESTAMP WHERE matches_last_seen_at IS NULL"
            )
        )

    if not insp.has_table("thread_read_states"):
        op.create_table(
            "thread_read_states",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("partner_user_id", sa.Integer(), nullable=False),
            sa.Column("last_read_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["partner_user_id"], ["users.id"]),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("user_id", "partner_user_id", name="uq_thread_read_pair"),
        )

    if insp.has_table("thread_read_states"):
        existing_indexes = {i["name"] for i in insp.get_indexes("thread_read_states")}
        if "ix_thread_read_states_user_id" not in existing_indexes:
            op.create_index("ix_thread_read_states_user_id", "thread_read_states", ["user_id"])
        if "ix_thread_read_states_partner_user_id" not in existing_indexes:
            op.create_index(
                "ix_thread_read_states_partner_user_id",
                "thread_read_states",
                ["partner_user_id"],
            )


def downgrade():
    op.drop_index("ix_thread_read_states_partner_user_id", table_name="thread_read_states")
    op.drop_index("ix_thread_read_states_user_id", table_name="thread_read_states")
    op.drop_table("thread_read_states")
    op.drop_column("users", "matches_last_seen_at")
