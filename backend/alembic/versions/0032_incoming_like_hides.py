"""Incoming like hides (premium likes screen).

Revision ID: 0032_incoming_like_hides
Revises: 0031_email_verification
"""

from alembic import op
import sqlalchemy as sa


revision = "0032_incoming_like_hides"
down_revision = "0031_email_verification"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "incoming_like_hides",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("viewer_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("admirer_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("viewer_user_id", "admirer_user_id", name="uq_incoming_like_hides_pair"),
        sa.CheckConstraint("viewer_user_id <> admirer_user_id", name="ck_incoming_like_hides_not_self"),
    )


def downgrade() -> None:
    op.drop_table("incoming_like_hides")
