"""Add gift cards and redemption tracking.

Revision ID: f5b8d6a4c3e2
Revises: e4a9c7d6b5f3
Create Date: 2026-07-28 17:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "f5b8d6a4c3e2"
down_revision = "e4a9c7d6b5f3"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "orders",
        sa.Column(
            "gift_card_redemption_amount",
            sa.Numeric(10, 2),
            nullable=True,
            server_default="0",
        ),
    )
    op.add_column("orders", sa.Column("gift_card_code", sa.String(length=40)))

    op.create_table(
        "gift_cards",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=40), nullable=False),
        sa.Column("initial_value", sa.Numeric(10, 2), nullable=False),
        sa.Column("current_balance", sa.Numeric(10, 2), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("purchased_by_user_id", sa.Integer(), nullable=True),
        sa.Column("recipient_email", sa.String(length=120), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("issued_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["purchased_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code"),
    )
    op.create_index("idx_gift_cards_status", "gift_cards", ["status"])

    op.create_table(
        "gift_card_transactions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("gift_card_id", sa.Integer(), nullable=False),
        sa.Column("order_id", sa.Integer(), nullable=True),
        sa.Column("amount_change", sa.Numeric(10, 2), nullable=False),
        sa.Column("transaction_type", sa.String(length=30), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["gift_card_id"], ["gift_cards.id"]),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_gift_card_transactions_card",
        "gift_card_transactions",
        ["gift_card_id", "created_at"],
    )

    op.execute(
        """
        INSERT INTO financial_categories
            (code, label, transaction_type, is_system, is_active, sort_order, created_at)
        SELECT
            'gift_card_liability',
            'Gift Card Liability',
            'liability',
            1,
            1,
            15,
            CURRENT_TIMESTAMP
        WHERE NOT EXISTS (
            SELECT 1 FROM financial_categories WHERE code = 'gift_card_liability'
        )
        """
    )


def downgrade():
    op.execute("DELETE FROM financial_categories WHERE code = 'gift_card_liability'")
    op.drop_index(
        "idx_gift_card_transactions_card", table_name="gift_card_transactions"
    )
    op.drop_table("gift_card_transactions")
    op.drop_index("idx_gift_cards_status", table_name="gift_cards")
    op.drop_table("gift_cards")
    op.drop_column("orders", "gift_card_code")
    op.drop_column("orders", "gift_card_redemption_amount")
