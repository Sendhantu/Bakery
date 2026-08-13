"""Add audit and branch portal foundation.

Revision ID: a9c1d4e7b8f2
Revises: a0b1c2d3e4f5
Create Date: 2026-08-13
"""

from alembic import op
import sqlalchemy as sa


revision = "a9c1d4e7b8f2"
down_revision = "a0b1c2d3e4f5"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "products",
        sa.Column(
            "production_source",
            sa.String(length=30),
            nullable=False,
            server_default="CENTRAL_KITCHEN",
        ),
    )

    op.create_table(
        "branch_product_assignments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("branch_id", sa.Integer(), sa.ForeignKey("branches.id"), nullable=False),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id"), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("branch_id", "product_id", name="uq_branch_product_assignment"),
    )
    op.create_index(
        "idx_branch_product_assignment_active",
        "branch_product_assignments",
        ["branch_id", "is_active"],
    )

    op.create_table(
        "branch_inventory",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("branch_id", sa.Integer(), sa.ForeignKey("branches.id"), nullable=False),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id")),
        sa.Column("raw_material_id", sa.Integer(), sa.ForeignKey("raw_materials.id")),
        sa.Column("quantity", sa.Numeric(10, 2), nullable=False, server_default="0"),
        sa.Column("reserved_quantity", sa.Numeric(10, 2), nullable=False, server_default="0"),
        sa.Column("min_stock", sa.Numeric(10, 2), nullable=False, server_default="0"),
        sa.Column("sync_status", sa.String(length=30), nullable=False, server_default="SYNCED"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("branch_id", "product_id", name="uq_branch_inventory_product"),
        sa.UniqueConstraint("branch_id", "raw_material_id", name="uq_branch_inventory_material"),
    )
    op.create_index(
        "idx_branch_inventory_branch_status",
        "branch_inventory",
        ["branch_id", "sync_status"],
    )

    op.create_table(
        "stock_transfers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("transfer_number", sa.String(length=80), nullable=False, unique=True),
        sa.Column("source_location", sa.String(length=80), nullable=False, server_default="CENTRAL_KITCHEN"),
        sa.Column("destination_branch_id", sa.Integer(), sa.ForeignKey("branches.id"), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="PREPARED"),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("received_by", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("prepared_at", sa.DateTime(), nullable=False),
        sa.Column("dispatched_at", sa.DateTime()),
        sa.Column("received_at", sa.DateTime()),
        sa.Column("idempotency_key", sa.String(length=120), unique=True),
        sa.Column("sync_status", sa.String(length=30), nullable=False, server_default="SYNCED"),
        sa.Column("notes", sa.Text()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime()),
    )
    op.create_index(
        "idx_stock_transfer_branch_status",
        "stock_transfers",
        ["destination_branch_id", "status"],
    )
    op.create_index("idx_stock_transfer_sync", "stock_transfers", ["sync_status", "updated_at"])

    op.create_table(
        "stock_transfer_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("transfer_id", sa.Integer(), sa.ForeignKey("stock_transfers.id"), nullable=False),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id")),
        sa.Column("raw_material_id", sa.Integer(), sa.ForeignKey("raw_materials.id")),
        sa.Column("quantity", sa.Numeric(10, 2), nullable=False),
        sa.Column("received_quantity", sa.Numeric(10, 2), nullable=False, server_default="0"),
    )
    op.create_index("idx_stock_transfer_item_transfer", "stock_transfer_items", ["transfer_id"])

    op.create_table(
        "branch_purchase_requests",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("request_number", sa.String(length=80), nullable=False, unique=True),
        sa.Column("branch_id", sa.Integer(), sa.ForeignKey("branches.id"), nullable=False),
        sa.Column("requested_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("priority", sa.String(length=20), nullable=False, server_default="normal"),
        sa.Column("reason", sa.Text()),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="DRAFT"),
        sa.Column("admin_response", sa.Text()),
        sa.Column("sync_status", sa.String(length=30), nullable=False, server_default="SYNCED"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime()),
        sa.Column("submitted_at", sa.DateTime()),
        sa.Column("reviewed_at", sa.DateTime()),
        sa.Column("reviewed_by", sa.Integer(), sa.ForeignKey("users.id")),
    )
    op.create_index(
        "idx_branch_purchase_request_branch_status",
        "branch_purchase_requests",
        ["branch_id", "status"],
    )
    op.create_index(
        "idx_branch_purchase_request_sync",
        "branch_purchase_requests",
        ["sync_status", "updated_at"],
    )

    op.create_table(
        "branch_purchase_request_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("request_id", sa.Integer(), sa.ForeignKey("branch_purchase_requests.id"), nullable=False),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id")),
        sa.Column("raw_material_id", sa.Integer(), sa.ForeignKey("raw_materials.id")),
        sa.Column("requested_quantity", sa.Numeric(10, 2), nullable=False),
        sa.Column("approved_quantity", sa.Numeric(10, 2)),
        sa.Column("notes", sa.Text()),
    )
    op.create_index(
        "idx_branch_purchase_request_item_request",
        "branch_purchase_request_items",
        ["request_id"],
    )

    op.create_table(
        "audit_documents",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("document_uid", sa.String(length=80), nullable=False, unique=True),
        sa.Column("financial_year", sa.String(length=20), nullable=False),
        sa.Column("category", sa.String(length=40), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("storage_reference", sa.String(length=500), nullable=False),
        sa.Column("original_filename", sa.String(length=255)),
        sa.Column("mime_type", sa.String(length=120)),
        sa.Column("size_bytes", sa.Integer(), server_default="0"),
        sa.Column("visibility", sa.String(length=30), nullable=False, server_default="AUDITOR"),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="DRAFT"),
        sa.Column("uploaded_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("uploaded_at", sa.DateTime(), nullable=False),
        sa.Column("published_at", sa.DateTime()),
    )
    op.create_index("idx_audit_document_year_status", "audit_documents", ["financial_year", "status"])
    op.create_index("idx_audit_document_category_status", "audit_documents", ["category", "status"])

    op.create_table(
        "audit_report_downloads",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("report_key", sa.String(length=80), nullable=False),
        sa.Column("financial_year", sa.String(length=20)),
        sa.Column("file_format", sa.String(length=20), nullable=False, server_default="csv"),
        sa.Column("portal_context", sa.String(length=40), nullable=False, server_default="audit"),
        sa.Column("ip_address", sa.String(length=64)),
        sa.Column("user_agent", sa.String(length=200)),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "idx_audit_report_download_user_created",
        "audit_report_downloads",
        ["user_id", "created_at"],
    )
    op.create_index(
        "idx_audit_report_download_report_created",
        "audit_report_downloads",
        ["report_key", "created_at"],
    )


def downgrade():
    op.drop_index("idx_audit_report_download_report_created", table_name="audit_report_downloads")
    op.drop_index("idx_audit_report_download_user_created", table_name="audit_report_downloads")
    op.drop_table("audit_report_downloads")
    op.drop_index("idx_audit_document_category_status", table_name="audit_documents")
    op.drop_index("idx_audit_document_year_status", table_name="audit_documents")
    op.drop_table("audit_documents")
    op.drop_index("idx_branch_purchase_request_item_request", table_name="branch_purchase_request_items")
    op.drop_table("branch_purchase_request_items")
    op.drop_index("idx_branch_purchase_request_sync", table_name="branch_purchase_requests")
    op.drop_index("idx_branch_purchase_request_branch_status", table_name="branch_purchase_requests")
    op.drop_table("branch_purchase_requests")
    op.drop_index("idx_stock_transfer_item_transfer", table_name="stock_transfer_items")
    op.drop_table("stock_transfer_items")
    op.drop_index("idx_stock_transfer_sync", table_name="stock_transfers")
    op.drop_index("idx_stock_transfer_branch_status", table_name="stock_transfers")
    op.drop_table("stock_transfers")
    op.drop_index("idx_branch_inventory_branch_status", table_name="branch_inventory")
    op.drop_table("branch_inventory")
    op.drop_index("idx_branch_product_assignment_active", table_name="branch_product_assignments")
    op.drop_table("branch_product_assignments")
    op.drop_column("products", "production_source")
