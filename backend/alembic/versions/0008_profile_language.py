"""Add preferred language to profiles.

Revision ID: 0008_profile_language
Revises: 0007_profile_verification
Create Date: 2026-04-22
"""

from alembic import op
import sqlalchemy as sa


revision = "0008_profile_language"
down_revision = "0007_profile_verification"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("profiles", sa.Column("preferred_language", sa.String(length=8), nullable=False, server_default="en"))


def downgrade() -> None:
    op.drop_column("profiles", "preferred_language")

