"""subscription periods

revision = "0003_subscription_periods"
down_revision = "0002_indexes"
"""

revision = "0003_subscription_periods"
down_revision = "0002_indexes"
branch_labels = None
depends_on = None

import sqlalchemy as sa
from alembic import op


def upgrade():
    op.add_column("subscriptions", sa.Column("start_date", sa.DateTime(), nullable=True))
    op.add_column("subscriptions", sa.Column("end_date", sa.DateTime(), nullable=True))


def downgrade():
    op.drop_column("subscriptions", "end_date")
    op.drop_column("subscriptions", "start_date")

