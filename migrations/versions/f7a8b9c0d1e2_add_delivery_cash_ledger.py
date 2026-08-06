"""add delivery cash ledger

Revision ID: f7a8b9c0d1e2
Revises: e6f7a8b9c0d1
Create Date: 2026-07-31 18:35:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "f7a8b9c0d1e2"
down_revision = "e6f7a8b9c0d1"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "delivery_cash_ledger",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("agent_id", sa.Integer(), nullable=False),
        sa.Column("order_id", sa.Integer(), nullable=True),
        sa.Column("action", sa.String(length=40), nullable=False),
        sa.Column("amount", sa.Numeric(10, 2), nullable=False),
        sa.Column("balance_after", sa.Numeric(10, 2), nullable=False),
        sa.Column("payment_mode", sa.String(length=40), nullable=True),
        sa.Column("recovery_method", sa.String(length=40), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("recorded_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["agent_id"], ["delivery_agents.id"]),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"]),
        sa.ForeignKeyConstraint(["recorded_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_delivery_cash_agent_created",
        "delivery_cash_ledger",
        ["agent_id", "created_at"],
    )
    op.create_index("idx_delivery_cash_order", "delivery_cash_ledger", ["order_id"])
    op.create_index("idx_delivery_cash_action", "delivery_cash_ledger", ["action"])


def downgrade():
    op.drop_index("idx_delivery_cash_action", table_name="delivery_cash_ledger")
    op.drop_index("idx_delivery_cash_order", table_name="delivery_cash_ledger")
    op.drop_index(
        "idx_delivery_cash_agent_created",
        table_name="delivery_cash_ledger",
    )
    op.drop_table("delivery_cash_ledger")
