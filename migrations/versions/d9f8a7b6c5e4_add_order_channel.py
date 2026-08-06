"""Add order channel for online and counter sales.

Revision ID: d9f8a7b6c5e4
Revises: c8e4f1a2b3d6
Create Date: 2026-07-28 15:10:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "d9f8a7b6c5e4"
down_revision = "c8e4f1a2b3d6"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "orders",
        sa.Column(
            "channel",
            sa.String(length=20),
            nullable=False,
            server_default="online",
        ),
    )
    op.execute(
        """
        UPDATE orders
        SET channel = CASE
            WHEN UPPER(COALESCE(source, '')) = 'POS' THEN 'counter'
            ELSE 'online'
        END
        """
    )
    if op.get_context().dialect.name != "sqlite":
        op.alter_column("orders", "channel", server_default=None)


def downgrade():
    op.drop_column("orders", "channel")
