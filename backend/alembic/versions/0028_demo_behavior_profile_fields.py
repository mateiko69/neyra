"""Demo living behavior: personality + scheduled reply state on profiles.

Revision ID: 0028_demo_behavior_profile_fields
Revises: 0027_referral_reward_grants
"""

from alembic import op
import sqlalchemy as sa


revision = "0028_demo_behavior_profile_fields"
down_revision = "0027_referral_reward_grants"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("profiles") as batch:
        batch.add_column(sa.Column("demo_personality_json", sa.Text(), nullable=False, server_default=sa.text("'{}'")))
        batch.add_column(sa.Column("demo_reply_scheduled_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("demo_pending_json", sa.Text(), nullable=False, server_default=sa.text("'{}'")))


def downgrade() -> None:
    try:
        with op.batch_alter_table("profiles") as batch:
            batch.drop_column("demo_pending_json")
            batch.drop_column("demo_reply_scheduled_at")
            batch.drop_column("demo_personality_json")
    except Exception:
        pass
