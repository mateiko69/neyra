"""initial"""
revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa

def upgrade():
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.String(length=255), nullable=False, unique=True),
        sa.Column("hashed_password", sa.String(length=255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.create_table(
        "profiles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False, unique=True),
        sa.Column("display_name", sa.String(length=100), nullable=False),
        sa.Column("bio", sa.Text(), nullable=False, server_default=""),
        sa.Column("age", sa.Integer(), nullable=True),
        sa.Column("city", sa.String(length=100), nullable=False, server_default=""),
        sa.Column("gender", sa.String(length=50), nullable=False, server_default=""),
        sa.Column("interested_in", sa.String(length=50), nullable=False, server_default=""),
        sa.Column("relationship_goal", sa.String(length=50), nullable=False, server_default="relationship"),
        sa.Column("interests", sa.Text(), nullable=False, server_default=""),
        sa.Column("lifestyle_tags", sa.Text(), nullable=False, server_default=""),
        sa.Column("photo_urls", sa.Text(), nullable=False, server_default=""),
        sa.Column("min_preferred_age", sa.Integer(), nullable=True),
        sa.Column("max_preferred_age", sa.Integer(), nullable=True),
    )

    op.create_table(
        "swipes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("swiper_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("target_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("liked", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )

    op.create_table(
        "matches",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_a_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("user_b_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("user_a_id", "user_b_id", name="uq_match_pair"),
    )

    op.create_table(
        "messages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("sender_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("receiver_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )

    op.create_table(
        "subscriptions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("provider_customer_id", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("provider_subscription_id", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="inactive"),
        sa.Column("plan_code", sa.String(length=50), nullable=False, server_default="free"),
    )

    op.create_table(
        "device_tokens",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("platform", sa.String(length=20), nullable=False),
        sa.Column("token", sa.String(length=255), nullable=False),
    )

    op.create_table(
        "analytics_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )

def downgrade():
    op.drop_table("analytics_events")
    op.drop_table("device_tokens")
    op.drop_table("subscriptions")
    op.drop_table("messages")
    op.drop_table("matches")
    op.drop_table("swipes")
    op.drop_table("profiles")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")
