"""Gallery rows for profile photos (S3/R2-backed URLs).

Revision ID: 0046_profile_photos
Revises: 0045_backfill_demo_profile_photo_urls

"""
from __future__ import annotations

from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision = "0046_profile_photos"
down_revision = "0045_backfill_demo_profile_photo_urls"


def upgrade() -> None:
    op.create_table(
        "profile_photos",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_profile_photos_user_id_sort", "profile_photos", ["user_id", "sort_order"])

    conn = op.get_bind()
    rows = conn.execute(sa.text("SELECT user_id, photo_urls, is_demo_profile FROM profiles")).fetchall()
    now = datetime.now(UTC)
    for uid, csv, is_demo in rows:
        if bool(is_demo):
            continue
        urls = [p.strip() for p in str(csv or "").split(",") if p.strip()]
        for i, url in enumerate(urls):
            conn.execute(
                sa.text(
                    "INSERT INTO profile_photos (user_id, url, sort_order, created_at) "
                    "VALUES (:uid, :url, :sort, :created)"
                ),
                {"uid": int(uid), "url": url, "sort": i, "created": now},
            )


def downgrade() -> None:
    op.drop_index("ix_profile_photos_user_id_sort", table_name="profile_photos")
    op.drop_table("profile_photos")
