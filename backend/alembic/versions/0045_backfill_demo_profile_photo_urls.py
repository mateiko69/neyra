"""Backfill demo bot profile photos away from ephemeral /uploads and remote placeholders.

Non-demo users keep stored URLs (even stale /uploads paths); SafeImg shows a placeholder on 404.

Revision ID: 0045_backfill_demo_profile_photo_urls
Revises: 0044_ai_usage_daily_counters
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0045_backfill_demo_profile_photo_urls"
down_revision = "0044_ai_usage_daily_counters"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    if conn.dialect.name != "postgresql":
        return

    # Demo/is_demo profiles only: map to bundled paths under /demo-profiles/shared (frontend public assets).
    conn.execute(
        sa.text(
            """
            UPDATE profiles AS p
            SET photo_urls = '/demo-profiles/shared/avatar-'
                || LPAD((MOD(ABS(hashtext(COALESCE(u.email, '') || '|' || COALESCE(p.gender, ''))), 12) + 1)::text, 2, '0')
                || '.jpg'
            FROM users AS u
            WHERE u.id = p.user_id
              AND (
                    u.is_demo = TRUE
                 OR LOWER(COALESCE(u.email, '')) LIKE 'demo+%@neyra.local'
                 OR p.is_demo_profile = TRUE
              )
              AND (
                    p.photo_urls LIKE '%/uploads/%'
                 OR p.photo_urls LIKE 'http://%'
                 OR p.photo_urls LIKE 'https://%'
                 OR TRIM(COALESCE(p.photo_urls, '')) = ''
              )
            """
        )
    )


def downgrade() -> None:
    pass
