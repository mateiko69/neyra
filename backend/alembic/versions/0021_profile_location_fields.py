"""Add normalized profile location fields.

Revision ID: 0021_profile_location_fields
Revises: 0020_ai_memory_and_events
Create Date: 2026-04-26
"""

from alembic import op
import sqlalchemy as sa


revision = "0021_profile_location_fields"
down_revision = "0020_ai_memory_and_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("profiles") as batch:
        batch.add_column(sa.Column("city_original", sa.String(length=100), nullable=False, server_default=""))
        batch.add_column(sa.Column("city_en", sa.String(length=100), nullable=False, server_default=""))
        batch.add_column(sa.Column("city_local", sa.String(length=100), nullable=False, server_default=""))
        batch.add_column(sa.Column("city_locative_uk", sa.String(length=100), nullable=False, server_default=""))
        batch.add_column(sa.Column("country_code", sa.String(length=2), nullable=False, server_default=""))
        batch.add_column(sa.Column("region", sa.String(length=64), nullable=False, server_default=""))
        batch.add_column(sa.Column("timezone", sa.String(length=64), nullable=False, server_default=""))


def downgrade() -> None:
    try:
        with op.batch_alter_table("profiles") as batch:
            batch.drop_column("timezone")
            batch.drop_column("region")
            batch.drop_column("country_code")
            batch.drop_column("city_locative_uk")
            batch.drop_column("city_local")
            batch.drop_column("city_en")
            batch.drop_column("city_original")
    except Exception:
        pass

