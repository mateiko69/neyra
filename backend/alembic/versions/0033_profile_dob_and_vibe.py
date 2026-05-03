"""Add profiles.date_of_birth and profiles.vibe.

Revision ID: 0033_profile_dob_and_vibe
Revises: 0032_incoming_like_hides
Create Date: 2026-04-29
"""

from alembic import op
import sqlalchemy as sa


revision = "0033_profile_dob_and_vibe"
down_revision = "0032_incoming_like_hides"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("profiles") as batch:
        batch.add_column(sa.Column("date_of_birth", sa.Date(), nullable=True))
        batch.add_column(sa.Column("vibe", sa.String(length=32), nullable=False, server_default=""))


def downgrade() -> None:
    try:
        with op.batch_alter_table("profiles") as batch:
            batch.drop_column("vibe")
            batch.drop_column("date_of_birth")
    except Exception:
        pass

