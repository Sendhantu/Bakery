"""add_revenue_analytics_indexes

Revision ID: 9f2b1a7c4e8d
Revises: eb6e5812aa59
Create Date: 2026-07-22 00:00:00.000000

"""
from alembic import op


# revision identifiers, used by Alembic.
revision = "9f2b1a7c4e8d"
down_revision = "eb6e5812aa59"
branch_labels = None
depends_on = None


def upgrade():
    op.create_index(
        "idx_order_status_payment_placed",
        "orders",
        ["status", "payment_status", "placed_at"],
        unique=False,
    )


def downgrade():
    op.drop_index("idx_order_status_payment_placed", table_name="orders")
