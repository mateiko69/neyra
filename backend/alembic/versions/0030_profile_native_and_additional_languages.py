"""Add profiles.native_language and profiles.additional_languages.

Revision ID: 0030_profile_native_and_additional_languages
Revises: 0029_profile_preferred_gender
"""

from alembic import op
import sqlalchemy as sa


revision = "0030_profile_native_and_additional_languages"
down_revision = "0029_profile_preferred_gender"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("profiles") as batch:
        batch.add_column(sa.Column("native_language", sa.String(length=8), nullable=False, server_default=""))
        batch.add_column(sa.Column("additional_languages", sa.Text(), nullable=False, server_default=""))


def downgrade() -> None:
    try:
        with op.batch_alter_table("profiles") as batch:
            batch.drop_column("additional_languages")
            batch.drop_column("native_language")
    except Exception:
        pass

