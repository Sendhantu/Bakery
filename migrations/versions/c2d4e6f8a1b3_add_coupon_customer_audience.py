"""add_coupon_customer_audience

Revision ID: c2d4e6f8a1b3
Revises: a8c6d4e2f9b1
Create Date: 2026-07-31 18:20:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "c2d4e6f8a1b3"
down_revision = "a8c6d4e2f9b1"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("coupons", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "customer_audience",
                sa.String(length=30),
                nullable=False,
                server_default="all",
            )
        )
        batch_op.add_column(
            sa.Column(
                "first_order_only",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )


def downgrade():
    with op.batch_alter_table("coupons", schema=None) as batch_op:
        batch_op.drop_column("first_order_only")
        batch_op.drop_column("customer_audience")
