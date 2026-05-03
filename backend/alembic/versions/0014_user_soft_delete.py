"""Add user soft-delete fields (30-day reversible deletion).

Revision ID: 0014_user_soft_delete
Revises: 0013_ai_trial_usage
Create Date: 2026-04-24
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0014_user_soft_delete"
down_revision = "0013_ai_trial_usage"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Postgres boolean defaults must be boolean literals (not integer 0/1).
    op.add_column("users", sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("users", sa.Column("deleted_at", sa.DateTime(), nullable=True))
    op.add_column("users", sa.Column("deletion_scheduled_for", sa.DateTime(), nullable=True))
    op.create_index("ix_users_is_deleted", "users", ["is_deleted"])
    op.create_index("ix_users_deletion_scheduled_for", "users", ["deletion_scheduled_for"])


def downgrade() -> None:
    op.drop_index("ix_users_deletion_scheduled_for", table_name="users")
    op.drop_index("ix_users_is_deleted", table_name="users")
    op.drop_column("users", "deletion_scheduled_for")
    op.drop_column("users", "deleted_at")
    op.drop_column("users", "is_deleted")

