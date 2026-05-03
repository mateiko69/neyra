"""Add visual embeddings to profiles.

Revision ID: 0006_visual_embeddings
Revises: 0005_oauth_accounts
Create Date: 2026-04-22
"""

from alembic import op
import sqlalchemy as sa


revision = "0006_visual_embeddings"
down_revision = "0005_oauth_accounts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("profiles", sa.Column("visual_embedding", sa.Text(), nullable=False, server_default=""))


def downgrade() -> None:
    op.drop_column("profiles", "visual_embedding")

