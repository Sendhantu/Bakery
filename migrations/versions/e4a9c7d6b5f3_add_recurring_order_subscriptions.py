"""Add recurring order subscriptions.

Revision ID: e4a9c7d6b5f3
Revises: d9f8a7b6c5e4
Create Date: 2026-07-28 16:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "e4a9c7d6b5f3"
down_revision = "d9f8a7b6c5e4"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "recurring_subscriptions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("branch_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("frequency", sa.String(length=20), nullable=False),
        sa.Column("days_of_week", sa.String(length=30), nullable=True),
        sa.Column("next_scheduled_date", sa.Date(), nullable=False),
        sa.Column(
            "payment_method_reference",
            sa.String(length=80),
            nullable=False,
            server_default="manual_payment_link",
        ),
        sa.Column("paused_until", sa.Date(), nullable=True),
        sa.Column("delivery_window", sa.String(length=50), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["branch_id"], ["branches.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_recurring_subscriptions_due",
        "recurring_subscriptions",
        ["status", "next_scheduled_date"],
    )
    op.create_index(
        "idx_recurring_subscriptions_user",
        "recurring_subscriptions",
        ["user_id", "status"],
    )

    op.create_table(
        "subscription_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("subscription_id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("variant_id", sa.Integer(), nullable=True),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"]),
        sa.ForeignKeyConstraint(
            ["subscription_id"],
            ["recurring_subscriptions.id"],
        ),
        sa.ForeignKeyConstraint(["variant_id"], ["product_variants.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_subscription_items_subscription",
        "subscription_items",
        ["subscription_id"],
    )

    op.create_table(
        "subscription_order_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("subscription_id", sa.Integer(), nullable=False),
        sa.Column("order_id", sa.Integer(), nullable=True),
        sa.Column("attempted_at", sa.DateTime(), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"]),
        sa.ForeignKeyConstraint(
            ["subscription_id"],
            ["recurring_subscriptions.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_subscription_order_logs_subscription",
        "subscription_order_logs",
        ["subscription_id", "attempted_at"],
    )


def downgrade():
    op.drop_index(
        "idx_subscription_order_logs_subscription",
        table_name="subscription_order_logs",
    )
    op.drop_table("subscription_order_logs")
    op.drop_index("idx_subscription_items_subscription", table_name="subscription_items")
    op.drop_table("subscription_items")
    op.drop_index(
        "idx_recurring_subscriptions_user",
        table_name="recurring_subscriptions",
    )
    op.drop_index(
        "idx_recurring_subscriptions_due",
        table_name="recurring_subscriptions",
    )
    op.drop_table("recurring_subscriptions")
