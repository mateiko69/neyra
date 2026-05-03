"""Add profile verification state machine fields.

Revision ID: 0012_profile_verification_state_machine
Revises: 0011_voice_messages
Create Date: 2026-04-23
"""

from alembic import op
import sqlalchemy as sa


revision = "0012_profile_verification_state_machine"
down_revision = "0011_voice_messages"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("profiles", sa.Column("verification_type", sa.String(length=16), nullable=False, server_default="manual"))
    op.add_column("profiles", sa.Column("verification_status", sa.String(length=16), nullable=False, server_default="none"))
    op.add_column("profiles", sa.Column("verification_updated_at", sa.DateTime(), nullable=True))
    op.add_column("profiles", sa.Column("verification_selfie_url", sa.Text(), nullable=False, server_default=""))


def downgrade() -> None:
    op.drop_column("profiles", "verification_selfie_url")
    op.drop_column("profiles", "verification_updated_at")
    op.drop_column("profiles", "verification_status")
    op.drop_column("profiles", "verification_type")

