"""Add customer activity tracking for AI context.

Revision ID: d1e2f3a4b5c6
Revises: c9d0e1f2a3b4
Create Date: 2026-08-03 13:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "d1e2f3a4b5c6"
down_revision = "c9d0e1f2a3b4"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "customer_activity",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("event_type", sa.String(length=40), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=True),
        sa.Column("query_text", sa.String(length=255), nullable=True),
        sa.Column("metadata_json", sa.Text(), nullable=True),
        sa.Column("session_id", sa.String(length=120), nullable=True),
        sa.Column("ip_address", sa.String(length=64), nullable=True),
        sa.Column("user_agent", sa.String(length=200), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_customer_activity_user_created",
        "customer_activity",
        ["user_id", "created_at"],
    )
    op.create_index(
        "idx_customer_activity_product_created",
        "customer_activity",
        ["product_id", "created_at"],
    )
    op.create_index(
        "idx_customer_activity_event_created",
        "customer_activity",
        ["event_type", "created_at"],
    )


def downgrade():
    op.drop_index("idx_customer_activity_event_created", table_name="customer_activity")
    op.drop_index("idx_customer_activity_product_created", table_name="customer_activity")
    op.drop_index("idx_customer_activity_user_created", table_name="customer_activity")
    op.drop_table("customer_activity")
