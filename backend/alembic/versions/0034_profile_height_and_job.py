"""Add profiles.height_cm and profiles.job_title.

Revision ID: 0034_profile_height_and_job
Revises: 0033_profile_dob_and_vibe
Create Date: 2026-04-29
"""

from alembic import op
import sqlalchemy as sa


revision = "0034_profile_height_and_job"
down_revision = "0033_profile_dob_and_vibe"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("profiles") as batch:
        batch.add_column(sa.Column("height_cm", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("job_title", sa.String(length=100), nullable=False, server_default=""))


def downgrade() -> None:
    try:
        with op.batch_alter_table("profiles") as batch:
            batch.drop_column("job_title")
            batch.drop_column("height_cm")
    except Exception:
        pass

