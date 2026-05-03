"""Add verification_level, verification_badge_visible; normalize status values."""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0037_profile_verification_v2"
down_revision = "0036_message_ai_generated"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("profiles") as batch:
        batch.add_column(sa.Column("verification_level", sa.String(length=16), nullable=False, server_default="none"))
        batch.add_column(
            sa.Column(
                "verification_badge_visible",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("true"),
            )
        )
    # Data backfill: approved -> verified, pending_review -> pending, rejected -> none
    op.execute("UPDATE profiles SET verification_status = 'verified' WHERE verification_status = 'approved'")
    op.execute("UPDATE profiles SET verification_status = 'pending' WHERE verification_status = 'pending_review'")
    op.execute("UPDATE profiles SET verification_status = 'none' WHERE verification_status = 'rejected'")
    op.execute(
        "UPDATE profiles SET verification_level = 'photo' WHERE verification_status = 'verified' AND (verification_level IS NULL OR verification_level = '' OR verification_level = 'none')"
    )


def downgrade() -> None:
    op.execute("UPDATE profiles SET verification_status = 'approved' WHERE verification_status = 'verified'")
    with op.batch_alter_table("profiles") as batch:
        batch.drop_column("verification_badge_visible")
        batch.drop_column("verification_level")
