"""add core indexes

revision = "0002_indexes"
down_revision = "0001_initial"
"""

revision = "0002_indexes"
down_revision = "0001_initial"
branch_labels = None
depends_on = None

from alembic import op


def upgrade():
    op.create_index("ix_profiles_user_id", "profiles", ["user_id"], unique=True)
    op.create_index("ix_swipes_swiper_id", "swipes", ["swiper_id"])
    op.create_index("ix_swipes_target_user_id", "swipes", ["target_user_id"])
    op.create_index("ix_matches_user_a_id", "matches", ["user_a_id"])
    op.create_index("ix_matches_user_b_id", "matches", ["user_b_id"])
    op.create_index("ix_messages_sender_id", "messages", ["sender_id"])
    op.create_index("ix_messages_receiver_id", "messages", ["receiver_id"])


def downgrade():
    op.drop_index("ix_messages_receiver_id", table_name="messages")
    op.drop_index("ix_messages_sender_id", table_name="messages")
    op.drop_index("ix_matches_user_b_id", table_name="matches")
    op.drop_index("ix_matches_user_a_id", table_name="matches")
    op.drop_index("ix_swipes_target_user_id", table_name="swipes")
    op.drop_index("ix_swipes_swiper_id", table_name="swipes")
    op.drop_index("ix_profiles_user_id", table_name="profiles")

