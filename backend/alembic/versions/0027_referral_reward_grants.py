"""Referral reward milestone grants (premium extension).

Revision ID: 0027_referral_reward_grants
Revises: 0026_user_referrals
"""

from alembic import op
import sqlalchemy as sa


revision = "0027_referral_reward_grants"
down_revision = "0026_user_referrals"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "referral_reward_grants",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("milestone_key", sa.String(length=16), nullable=False),
        sa.Column("premium_days", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("user_id", "milestone_key", name="uq_referral_reward_user_milestone"),
    )
    op.create_index("ix_referral_reward_grants_user_id", "referral_reward_grants", ["user_id"], unique=False)


def downgrade() -> None:
    try:
        op.drop_index("ix_referral_reward_grants_user_id", table_name="referral_reward_grants")
    except Exception:
        pass
    try:
        op.drop_table("referral_reward_grants")
    except Exception:
        pass
