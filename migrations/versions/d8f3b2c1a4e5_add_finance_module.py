"""add_finance_module

Revision ID: d8f3b2c1a4e5
Revises: c7e2a1b9f4d3
Create Date: 2026-07-22 20:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "d8f3b2c1a4e5"
down_revision = "c7e2a1b9f4d3"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "financial_categories",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=60), nullable=False),
        sa.Column("label", sa.String(length=120), nullable=False),
        sa.Column("transaction_type", sa.String(length=20), nullable=False),
        sa.Column("is_system", sa.Boolean(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code"),
    )

    op.create_table(
        "tax_rates",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("code", sa.String(length=60), nullable=False),
        sa.Column("rate_percent", sa.Numeric(precision=6, scale=3), nullable=False),
        sa.Column("applies_to", sa.String(length=60)),
        sa.Column("product_category_id", sa.Integer(), nullable=True),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["product_category_id"], ["categories.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code"),
    )

    op.create_table(
        "financial_transactions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("transaction_type", sa.String(length=20), nullable=False),
        sa.Column("category_id", sa.Integer(), nullable=False),
        sa.Column("amount", sa.LargeBinary(), nullable=False),
        sa.Column("tax_amount", sa.LargeBinary(), nullable=True),
        sa.Column("description", sa.LargeBinary(), nullable=True),
        sa.Column("counterparty", sa.LargeBinary(), nullable=True),
        sa.Column("reference_order_id", sa.Integer(), nullable=True),
        sa.Column("reference_stock_movement_id", sa.Integer(), nullable=True),
        sa.Column("branch_id", sa.Integer(), nullable=True),
        sa.Column("store_location", sa.String(length=150), nullable=True),
        sa.Column("tds_withheld", sa.LargeBinary(), nullable=True),
        sa.Column("is_auto_generated", sa.Boolean(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=120), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["branch_id"], ["branches.id"]),
        sa.ForeignKeyConstraint(["category_id"], ["financial_categories.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["reference_order_id"], ["orders.id"]),
        sa.ForeignKeyConstraint(["reference_stock_movement_id"], ["stock_movements.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key"),
    )
    op.create_index("idx_fin_txn_type_created", "financial_transactions", ["transaction_type", "created_at"])
    op.create_index("idx_fin_txn_branch_created", "financial_transactions", ["branch_id", "created_at"])
    op.create_index("idx_fin_txn_order", "financial_transactions", ["reference_order_id"])
    op.create_index("idx_fin_txn_movement", "financial_transactions", ["reference_stock_movement_id"])

    op.create_table(
        "tax_records",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("period_type", sa.String(length=20), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("gst_collected", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("gst_paid", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("net_gst_liability", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("tds_withheld", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("admin_adjustment_notes", sa.Text(), nullable=True),
        sa.Column("computed_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("period_type", "period_start", "period_end", name="uq_tax_record_period"),
    )

    categories = sa.table(
        "financial_categories",
        sa.column("code", sa.String),
        sa.column("label", sa.String),
        sa.column("transaction_type", sa.String),
        sa.column("is_system", sa.Boolean),
        sa.column("is_active", sa.Boolean),
        sa.column("sort_order", sa.Integer),
        sa.column("created_at", sa.DateTime),
    )
    from datetime import date, datetime

    now = datetime.utcnow()
    seed_date = date(2020, 1, 1)
    op.bulk_insert(
        categories,
        [
            {"code": "sales", "label": "Sales", "transaction_type": "income", "is_system": True, "is_active": True, "sort_order": 10, "created_at": now},
            {"code": "raw_material_purchase", "label": "Raw Material Purchase", "transaction_type": "expense", "is_system": True, "is_active": True, "sort_order": 20, "created_at": now},
            {"code": "rent", "label": "Rent", "transaction_type": "expense", "is_system": True, "is_active": True, "sort_order": 30, "created_at": now},
            {"code": "utilities", "label": "Utilities", "transaction_type": "expense", "is_system": True, "is_active": True, "sort_order": 40, "created_at": now},
            {"code": "salary", "label": "Salary", "transaction_type": "expense", "is_system": True, "is_active": True, "sort_order": 50, "created_at": now},
            {"code": "other_income", "label": "Other Income", "transaction_type": "income", "is_system": True, "is_active": True, "sort_order": 60, "created_at": now},
            {"code": "other_expense", "label": "Other Expense", "transaction_type": "expense", "is_system": True, "is_active": True, "sort_order": 70, "created_at": now},
        ],
    )

    tax_rates = sa.table(
        "tax_rates",
        sa.column("name", sa.String),
        sa.column("code", sa.String),
        sa.column("rate_percent", sa.Numeric),
        sa.column("applies_to", sa.String),
        sa.column("effective_from", sa.Date),
        sa.column("is_active", sa.Boolean),
        sa.column("created_at", sa.DateTime),
    )
    op.bulk_insert(
        tax_rates,
        [
            {
                "name": "Default GST (5%)",
                "code": "gst_default_5",
                "rate_percent": 5,
                "applies_to": "sales",
                "effective_from": seed_date,
                "is_active": True,
                "created_at": now,
            }
        ],
    )


def downgrade():
    op.drop_table("tax_records")
    op.drop_index("idx_fin_txn_movement", table_name="financial_transactions")
    op.drop_index("idx_fin_txn_order", table_name="financial_transactions")
    op.drop_index("idx_fin_txn_branch_created", table_name="financial_transactions")
    op.drop_index("idx_fin_txn_type_created", table_name="financial_transactions")
    op.drop_table("financial_transactions")
    op.drop_table("tax_rates")
    op.drop_table("financial_categories")
