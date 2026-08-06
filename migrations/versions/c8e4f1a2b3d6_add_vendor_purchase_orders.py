"""add vendor purchase orders

Revision ID: c8e4f1a2b3d6
Revises: b7e5c1a9d2f3
Create Date: 2026-07-28 15:50:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "c8e4f1a2b3d6"
down_revision = "b7e5c1a9d2f3"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "vendors",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column("contact_person", sa.String(length=120), nullable=True),
        sa.Column("phone", sa.String(length=30), nullable=True),
        sa.Column("email", sa.String(length=120), nullable=True),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("payment_terms", sa.String(length=120), nullable=True),
        sa.Column("gstin", sa.String(length=20), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_table(
        "purchase_orders",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("vendor_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("order_date", sa.Date(), nullable=False),
        sa.Column("expected_delivery_date", sa.Date(), nullable=True),
        sa.Column("received_at", sa.DateTime(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("gst_rate_percent", sa.Numeric(6, 3), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["vendor_id"], ["vendors.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_purchase_order_vendor", "purchase_orders", ["vendor_id"])
    op.create_index("idx_purchase_order_status", "purchase_orders", ["status"])
    op.create_index("idx_purchase_order_order_date", "purchase_orders", ["order_date"])
    op.create_table(
        "vendor_products",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("vendor_id", sa.Integer(), nullable=False),
        sa.Column("raw_material_id", sa.Integer(), nullable=False),
        sa.Column("typical_unit_cost", sa.Numeric(10, 2), nullable=True),
        sa.Column("last_unit_cost", sa.Numeric(10, 2), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["raw_material_id"], ["raw_materials.id"]),
        sa.ForeignKeyConstraint(["vendor_id"], ["vendors.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "vendor_id", "raw_material_id", name="uq_vendor_raw_material"
        ),
    )
    op.create_index("idx_vendor_product_vendor", "vendor_products", ["vendor_id"])
    op.create_index(
        "idx_vendor_product_material", "vendor_products", ["raw_material_id"]
    )
    op.create_table(
        "purchase_order_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("purchase_order_id", sa.Integer(), nullable=False),
        sa.Column("raw_material_id", sa.Integer(), nullable=False),
        sa.Column("quantity", sa.Numeric(10, 2), nullable=False),
        sa.Column("unit_cost", sa.Numeric(10, 2), nullable=False),
        sa.ForeignKeyConstraint(["purchase_order_id"], ["purchase_orders.id"]),
        sa.ForeignKeyConstraint(["raw_material_id"], ["raw_materials.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_purchase_order_item_order", "purchase_order_items", ["purchase_order_id"]
    )
    op.create_index(
        "idx_purchase_order_item_material", "purchase_order_items", ["raw_material_id"]
    )
    with op.batch_alter_table("financial_transactions", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("reference_purchase_order_id", sa.Integer(), nullable=True)
        )
        batch_op.add_column(sa.Column("vendor_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_financial_transactions_purchase_order",
            "purchase_orders",
            ["reference_purchase_order_id"],
            ["id"],
        )
        batch_op.create_foreign_key(
            "fk_financial_transactions_vendor",
            "vendors",
            ["vendor_id"],
            ["id"],
        )
    op.create_index(
        "idx_fin_txn_purchase_order",
        "financial_transactions",
        ["reference_purchase_order_id"],
    )
    op.create_index(
        "idx_fin_txn_vendor_created",
        "financial_transactions",
        ["vendor_id", "created_at"],
    )


def downgrade():
    op.drop_index("idx_fin_txn_vendor_created", table_name="financial_transactions")
    op.drop_index("idx_fin_txn_purchase_order", table_name="financial_transactions")
    with op.batch_alter_table("financial_transactions", schema=None) as batch_op:
        batch_op.drop_constraint(
            "fk_financial_transactions_vendor",
            type_="foreignkey",
        )
        batch_op.drop_constraint(
            "fk_financial_transactions_purchase_order",
            type_="foreignkey",
        )
        batch_op.drop_column("vendor_id")
        batch_op.drop_column("reference_purchase_order_id")
    op.drop_index("idx_purchase_order_item_material", table_name="purchase_order_items")
    op.drop_index("idx_purchase_order_item_order", table_name="purchase_order_items")
    op.drop_table("purchase_order_items")
    op.drop_index("idx_vendor_product_material", table_name="vendor_products")
    op.drop_index("idx_vendor_product_vendor", table_name="vendor_products")
    op.drop_table("vendor_products")
    op.drop_index("idx_purchase_order_order_date", table_name="purchase_orders")
    op.drop_index("idx_purchase_order_status", table_name="purchase_orders")
    op.drop_index("idx_purchase_order_vendor", table_name="purchase_orders")
    op.drop_table("purchase_orders")
    op.drop_table("vendors")
