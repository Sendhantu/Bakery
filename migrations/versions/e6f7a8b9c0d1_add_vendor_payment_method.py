"""add vendor payment method

Revision ID: e6f7a8b9c0d1
Revises: c2d4e6f8a1b3
Create Date: 2026-07-31 18:05:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "e6f7a8b9c0d1"
down_revision = "c2d4e6f8a1b3"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("financial_transactions", schema=None) as batch_op:
        batch_op.add_column(sa.Column("payment_method", sa.String(length=60), nullable=True))


def downgrade():
    with op.batch_alter_table("financial_transactions", schema=None) as batch_op:
        batch_op.drop_column("payment_method")
