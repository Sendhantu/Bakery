"""Add raw material detail fields, batch tracking, and documents.

Revision ID: c3e5a7b9d1f3
Revises: a4d6e8f0b2c4
Create Date: 2026-08-06 10:30:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "c3e5a7b9d1f3"
down_revision = "a4d6e8f0b2c4"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("raw_materials") as batch_op:
        batch_op.add_column(sa.Column("sku", sa.String(length=60), nullable=True))
        batch_op.add_column(sa.Column("category", sa.String(length=80), nullable=True))
        batch_op.add_column(
            sa.Column(
                "reserved_quantity",
                sa.Numeric(10, 2),
                nullable=False,
                server_default="0",
            )
        )
        batch_op.add_column(sa.Column("min_stock", sa.Numeric(10, 2), nullable=True))
        batch_op.add_column(sa.Column("max_stock", sa.Numeric(10, 2), nullable=True))
        batch_op.add_column(
            sa.Column("preferred_supplier_id", sa.Integer(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("storage_location", sa.String(length=150), nullable=True)
        )
        batch_op.add_column(sa.Column("shelf_life_days", sa.Integer(), nullable=True))
        batch_op.add_column(
            sa.Column("tax_rate_percent", sa.Numeric(6, 3), nullable=True)
        )
        batch_op.add_column(
            sa.Column(
                "expiring_soon_days",
                sa.Integer(),
                nullable=False,
                server_default="14",
            )
        )
        batch_op.add_column(
            sa.Column("last_purchased_at", sa.DateTime(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("last_purchase_quantity", sa.Numeric(10, 2), nullable=True)
        )
        batch_op.add_column(
            sa.Column("last_purchase_unit_price", sa.Numeric(10, 2), nullable=True)
        )
        batch_op.add_column(sa.Column("updated_by", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_raw_materials_preferred_supplier",
            "vendors",
            ["preferred_supplier_id"],
            ["id"],
        )
        batch_op.create_foreign_key(
            "fk_raw_materials_updated_by",
            "users",
            ["updated_by"],
            ["id"],
        )
        batch_op.create_index("idx_raw_material_category", ["category"])
        batch_op.create_index("idx_raw_material_supplier", ["preferred_supplier_id"])

    with op.batch_alter_table("stock_movements") as batch_op:
        batch_op.add_column(sa.Column("notes", sa.Text(), nullable=True))
        batch_op.add_column(
            sa.Column("reference_purchase_order_id", sa.Integer(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("reference_batch_id", sa.Integer(), nullable=True)
        )
        batch_op.create_foreign_key(
            "fk_stock_movements_po",
            "purchase_orders",
            ["reference_purchase_order_id"],
            ["id"],
        )
        batch_op.create_foreign_key(
            "fk_stock_movements_batch",
            "material_batches",
            ["reference_batch_id"],
            ["id"],
        )
        batch_op.create_index("idx_stock_movement_po", ["reference_purchase_order_id"])
        batch_op.create_index("idx_stock_movement_batch", ["reference_batch_id"])

    op.create_table(
        "material_batches",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("raw_material_id", sa.Integer(), nullable=False),
        sa.Column("batch_number", sa.String(length=120), nullable=False),
        sa.Column("supplier_id", sa.Integer(), nullable=True),
        sa.Column("purchase_order_id", sa.Integer(), nullable=True),
        sa.Column("received_quantity", sa.Numeric(10, 2), nullable=False),
        sa.Column("remaining_quantity", sa.Numeric(10, 2), nullable=False),
        sa.Column("unit_cost", sa.Numeric(10, 2), nullable=True),
        sa.Column("manufacturing_date", sa.Date(), nullable=True),
        sa.Column("expiry_date", sa.Date(), nullable=True),
        sa.Column("storage_location", sa.String(length=150), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("received_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["raw_material_id"], ["raw_materials.id"]),
        sa.ForeignKeyConstraint(["supplier_id"], ["vendors.id"]),
        sa.ForeignKeyConstraint(["purchase_order_id"], ["purchase_orders.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_material_batch_material_status",
        "material_batches",
        ["raw_material_id", "status"],
    )
    op.create_index("idx_material_batch_expiry", "material_batches", ["expiry_date"])
    op.create_index("idx_material_batch_po", "material_batches", ["purchase_order_id"])

    op.create_table(
        "material_documents",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("raw_material_id", sa.Integer(), nullable=False),
        sa.Column("purchase_order_id", sa.Integer(), nullable=True),
        sa.Column("doc_type", sa.String(length=40), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("stored_path", sa.String(length=500), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=True),
        sa.Column("uploaded_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["raw_material_id"], ["raw_materials.id"]),
        sa.ForeignKeyConstraint(["purchase_order_id"], ["purchase_orders.id"]),
        sa.ForeignKeyConstraint(["uploaded_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_material_doc_material", "material_documents", ["raw_material_id"])
    op.create_index("idx_material_doc_po", "material_documents", ["purchase_order_id"])


def downgrade():
    with op.batch_alter_table("stock_movements") as batch_op:
        batch_op.drop_index("idx_stock_movement_batch")
        batch_op.drop_index("idx_stock_movement_po")
        batch_op.drop_constraint("fk_stock_movements_batch", type_="foreignkey")
        batch_op.drop_constraint("fk_stock_movements_po", type_="foreignkey")
        batch_op.drop_column("reference_batch_id")
        batch_op.drop_column("reference_purchase_order_id")
        batch_op.drop_column("notes")
    op.drop_table("material_documents")
    op.drop_table("material_batches")
    with op.batch_alter_table("raw_materials") as batch_op:
        batch_op.drop_index("idx_raw_material_supplier")
        batch_op.drop_index("idx_raw_material_category")
        batch_op.drop_constraint("fk_raw_materials_updated_by", type_="foreignkey")
        batch_op.drop_constraint(
            "fk_raw_materials_preferred_supplier", type_="foreignkey"
        )
        batch_op.drop_column("updated_by")
        batch_op.drop_column("last_purchase_unit_price")
        batch_op.drop_column("last_purchase_quantity")
        batch_op.drop_column("last_purchased_at")
        batch_op.drop_column("expiring_soon_days")
        batch_op.drop_column("tax_rate_percent")
        batch_op.drop_column("shelf_life_days")
        batch_op.drop_column("storage_location")
        batch_op.drop_column("preferred_supplier_id")
        batch_op.drop_column("max_stock")
        batch_op.drop_column("min_stock")
        batch_op.drop_column("reserved_quantity")
        batch_op.drop_column("category")
        batch_op.drop_column("sku")
