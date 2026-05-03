"""Add profile verification fields.

Revision ID: 0007_profile_verification
Revises: 0006_visual_embeddings
Create Date: 2026-04-22
"""

from alembic import op
import sqlalchemy as sa


revision = "0007_profile_verification"
down_revision = "0006_visual_embeddings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("profiles", sa.Column("verified", sa.Boolean(), nullable=False, server_default=sa.text("FALSE")))
    op.add_column("profiles", sa.Column("verified_at", sa.DateTime(), nullable=True))
    op.add_column("profiles", sa.Column("verification_embedding", sa.Text(), nullable=False, server_default=""))


def downgrade() -> None:
    op.drop_column("profiles", "verification_embedding")
    op.drop_column("profiles", "verified_at")
    op.drop_column("profiles", "verified")

