"""Add GST channel reporting fields.

Revision ID: f3a4b5c6d7e8
Revises: e2f3a4b5c6d7
Create Date: 2026-08-03 15:20:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "f3a4b5c6d7e8"
down_revision = "e2f3a4b5c6d7"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("orders", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "gst_taxable_amount",
                sa.Numeric(10, 2),
                nullable=False,
                server_default="0",
            )
        )
        batch_op.add_column(
            sa.Column(
                "cgst_amount",
                sa.Numeric(10, 2),
                nullable=False,
                server_default="0",
            )
        )
        batch_op.add_column(
            sa.Column(
                "sgst_amount",
                sa.Numeric(10, 2),
                nullable=False,
                server_default="0",
            )
        )
        batch_op.add_column(
            sa.Column(
                "gst_supply_type",
                sa.String(length=40),
                nullable=False,
                server_default="RESTAURANT_SERVICE",
            )
        )
        batch_op.add_column(
            sa.Column(
                "gst_order_source",
                sa.String(length=40),
                nullable=False,
                server_default="DIRECT_WEB_DELIVERY",
            )
        )
        batch_op.add_column(
            sa.Column(
                "gst_liability_party",
                sa.String(length=40),
                nullable=False,
                server_default="PAYABLE_BY_BAKERY",
            )
        )
        batch_op.add_column(
            sa.Column(
                "gst_return_bucket",
                sa.String(length=40),
                nullable=False,
                server_default="GSTR1_OUTWARD_SUPPLIES",
            )
        )
        batch_op.add_column(sa.Column("gst_invoice_note", sa.String(length=255)))
        batch_op.add_column(sa.Column("ecommerce_operator", sa.String(length=40)))
        batch_op.add_column(
            sa.Column(
                "ecommerce_tcs_amount",
                sa.Numeric(10, 2),
                nullable=False,
                server_default="0",
            )
        )
        batch_op.create_index("idx_order_gst_source", ["gst_order_source"])
        batch_op.create_index("idx_order_gst_liability", ["gst_liability_party"])

    op.execute(
        """
        UPDATE orders
        SET gst_taxable_amount = CASE
            WHEN (
                COALESCE(subtotal, 0)
                - COALESCE(discount, 0)
                - COALESCE(loyalty_discount, 0)
            ) > 0
            THEN ROUND(
                COALESCE(subtotal, 0)
                - COALESCE(discount, 0)
                - COALESCE(loyalty_discount, 0),
                2
            )
            ELSE 0
        END,
        cgst_amount = ROUND(COALESCE(gst_amount, 0) / 2, 2),
        sgst_amount = ROUND(
            COALESCE(gst_amount, 0) - ROUND(COALESCE(gst_amount, 0) / 2, 2),
            2
        )
        """
    )
    op.execute(
        """
        UPDATE orders
        SET gst_order_source = CASE
            WHEN UPPER(COALESCE(source, '')) IN ('SWIGGY', 'ECOMMERCE_SWIGGY') THEN 'ECOMMERCE_SWIGGY'
            WHEN UPPER(COALESCE(source, '')) IN ('ZOMATO', 'ECOMMERCE_ZOMATO') THEN 'ECOMMERCE_ZOMATO'
            WHEN LOWER(COALESCE(channel, '')) = 'counter' THEN 'COUNTER_TAKEAWAY'
            WHEN UPPER(COALESCE(fulfillment_type, '')) = 'PICKUP' THEN 'DIRECT_WEB_PICKUP'
            ELSE 'DIRECT_WEB_DELIVERY'
        END
        """
    )
    op.execute(
        """
        UPDATE orders
        SET gst_liability_party = CASE
            WHEN gst_order_source IN ('ECOMMERCE_SWIGGY', 'ECOMMERCE_ZOMATO') THEN 'PAID_BY_ECOMMERCE_OPERATOR'
            ELSE 'PAYABLE_BY_BAKERY'
        END,
        gst_return_bucket = CASE
            WHEN gst_order_source IN ('ECOMMERCE_SWIGGY', 'ECOMMERCE_ZOMATO') THEN 'GSTR1_TABLE_14_9_5'
            ELSE 'GSTR1_OUTWARD_SUPPLIES'
        END,
        gst_invoice_note = CASE
            WHEN gst_order_source IN ('ECOMMERCE_SWIGGY', 'ECOMMERCE_ZOMATO')
            THEN 'Tax to be deposited by E-commerce Operator under Section 9(5) of the CGST Act.'
            ELSE gst_invoice_note
        END,
        ecommerce_operator = CASE
            WHEN gst_order_source = 'ECOMMERCE_SWIGGY' THEN 'SWIGGY'
            WHEN gst_order_source = 'ECOMMERCE_ZOMATO' THEN 'ZOMATO'
            ELSE ecommerce_operator
        END,
        ecommerce_tcs_amount = CASE
            WHEN gst_order_source IN ('ECOMMERCE_SWIGGY', 'ECOMMERCE_ZOMATO')
            THEN ROUND(COALESCE(gst_taxable_amount, 0) * 0.01, 2)
            ELSE 0
        END
        """
    )


def downgrade():
    with op.batch_alter_table("orders", schema=None) as batch_op:
        batch_op.drop_index("idx_order_gst_liability")
        batch_op.drop_index("idx_order_gst_source")
        batch_op.drop_column("ecommerce_tcs_amount")
        batch_op.drop_column("ecommerce_operator")
        batch_op.drop_column("gst_invoice_note")
        batch_op.drop_column("gst_return_bucket")
        batch_op.drop_column("gst_liability_party")
        batch_op.drop_column("gst_order_source")
        batch_op.drop_column("gst_supply_type")
        batch_op.drop_column("sgst_amount")
        batch_op.drop_column("cgst_amount")
        batch_op.drop_column("gst_taxable_amount")
