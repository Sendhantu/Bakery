"""Add POS payment terminal transactions.

Revision ID: a0b1c2d3e4f5
Revises: f9a0b1c2d3e4
Create Date: 2026-08-09
"""

from alembic import op
import sqlalchemy as sa


revision = "a0b1c2d3e4f5"
down_revision = "f9a0b1c2d3e4"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "pos_payment_transactions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("transaction_id", sa.String(80), nullable=False, unique=True),
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("orders.id")),
        sa.Column("payment_id", sa.Integer(), sa.ForeignKey("payments.id")),
        sa.Column("amount", sa.Numeric(10, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="INR"),
        sa.Column("payment_method", sa.String(40), nullable=False),
        sa.Column("payment_status", sa.String(30), nullable=False, server_default="PENDING"),
        sa.Column("cash_received", sa.Numeric(10, 2)),
        sa.Column("change_returned", sa.Numeric(10, 2)),
        sa.Column("transaction_reference", sa.String(120)),
        sa.Column("method_details_json", sa.Text()),
        sa.Column("notes", sa.Text()),
        sa.Column("cashier_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("branch_id", sa.Integer(), sa.ForeignKey("branches.id")),
        sa.Column("idempotency_key", sa.String(120), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime()),
    )
    op.create_index("idx_pos_payment_created", "pos_payment_transactions", ["created_at"])
    op.create_index("idx_pos_payment_cashier_created", "pos_payment_transactions", ["cashier_id", "created_at"])
    op.create_index("idx_pos_payment_order", "pos_payment_transactions", ["order_id"])


def downgrade():
    op.drop_index("idx_pos_payment_order", table_name="pos_payment_transactions")
    op.drop_index("idx_pos_payment_cashier_created", table_name="pos_payment_transactions")
    op.drop_index("idx_pos_payment_created", table_name="pos_payment_transactions")
    op.drop_table("pos_payment_transactions")
