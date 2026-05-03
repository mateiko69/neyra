"""Email verification fields + tokens table.

Revision ID: 0031_email_verification
Revises: 0030_profile_native_and_additional_languages
"""

from alembic import op
import sqlalchemy as sa


revision = "0031_email_verification"
down_revision = "0030_profile_native_and_additional_languages"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch:
        # PostgreSQL: BOOLEAN defaults must be true/false (not 1/0).
        batch.add_column(sa.Column("email_verified", sa.Boolean(), nullable=False, server_default=sa.text("false")))
        batch.add_column(sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True))

    # Best practice: remove server default after backfilling existing rows.
    # Use a safe wrapper to avoid sqlite/batch quirks in dev.
    try:
        op.alter_column("users", "email_verified", server_default=None)
    except Exception:
        try:
            with op.batch_alter_table("users") as batch:
                batch.alter_column("email_verified", server_default=None)
        except Exception:
            pass

    op.create_table(
        "email_verification_tokens",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("token_hash", sa.String(length=128), nullable=False, index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    try:
        op.drop_table("email_verification_tokens")
    except Exception:
        pass
    try:
        with op.batch_alter_table("users") as batch:
            batch.drop_column("email_verified_at")
            batch.drop_column("email_verified")
    except Exception:
        pass

