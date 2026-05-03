"""oauth accounts and nullable password for social users

Idempotent guards: some environments may have partially-created tables.
This migration must not fail with "relation already exists".
"""

revision = "0005_oauth_accounts"
down_revision = "0004_nav_badges"
branch_labels = None
depends_on = None

import sqlalchemy as sa
from alembic import op


def upgrade():
    insp = sa.inspect(op.get_bind())

    # This alter is safe to run repeatedly.
    op.alter_column("users", "hashed_password", existing_type=sa.String(length=255), nullable=True)

    if not insp.has_table("oauth_accounts"):
        op.create_table(
            "oauth_accounts",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("provider", sa.String(length=32), nullable=False),
            sa.Column("provider_user_id", sa.String(length=255), nullable=False),
            sa.Column("email_snapshot", sa.String(length=255), nullable=True),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("provider", "provider_user_id", name="uq_oauth_provider_sub"),
            sa.UniqueConstraint("user_id", "provider", name="uq_oauth_user_provider"),
        )

    if insp.has_table("oauth_accounts"):
        existing_indexes = {i["name"] for i in insp.get_indexes("oauth_accounts")}
        if "ix_oauth_accounts_user_id" not in existing_indexes:
            op.create_index("ix_oauth_accounts_user_id", "oauth_accounts", ["user_id"])
        if "ix_oauth_accounts_provider" not in existing_indexes:
            op.create_index("ix_oauth_accounts_provider", "oauth_accounts", ["provider"])


def downgrade():
    op.drop_index("ix_oauth_accounts_provider", table_name="oauth_accounts")
    op.drop_index("ix_oauth_accounts_user_id", table_name="oauth_accounts")
    op.drop_table("oauth_accounts")
    op.alter_column("users", "hashed_password", existing_type=sa.String(length=255), nullable=False)
