"""User referral codes and referred_by tracking.

Revision ID: 0026_user_referrals
Revises: 0025_founder_welcome_demo_mode
"""

from alembic import op
import sqlalchemy as sa


revision = "0026_user_referrals"
down_revision = "0025_founder_welcome_demo_mode"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("referral_code", sa.String(length=16), nullable=True))
        batch.add_column(sa.Column("referred_by_user_id", sa.Integer(), nullable=True))
    op.create_index("ix_users_referral_code", "users", ["referral_code"], unique=True)
    op.create_index("ix_users_referred_by_user_id", "users", ["referred_by_user_id"], unique=False)
    try:
        op.create_foreign_key(
            "fk_users_referred_by_user_id",
            "users",
            "users",
            ["referred_by_user_id"],
            ["id"],
            ondelete="SET NULL",
        )
    except Exception:
        pass


def downgrade() -> None:
    try:
        op.drop_constraint("fk_users_referred_by_user_id", "users", type_="foreignkey")
    except Exception:
        pass
    try:
        op.drop_index("ix_users_referred_by_user_id", table_name="users")
    except Exception:
        pass
    try:
        op.drop_index("ix_users_referral_code", table_name="users")
    except Exception:
        pass
    try:
        with op.batch_alter_table("users") as batch:
            batch.drop_column("referred_by_user_id")
            batch.drop_column("referral_code")
    except Exception:
        pass
