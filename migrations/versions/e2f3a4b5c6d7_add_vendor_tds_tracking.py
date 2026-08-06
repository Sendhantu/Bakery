"""Add vendor TDS tracking.

Revision ID: e2f3a4b5c6d7
Revises: d1e2f3a4b5c6
Create Date: 2026-08-03 14:10:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "e2f3a4b5c6d7"
down_revision = "d1e2f3a4b5c6"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("vendors", schema=None) as batch_op:
        batch_op.add_column(sa.Column("pan", sa.String(length=20), nullable=True))
        batch_op.add_column(
            sa.Column(
                "tds_enabled",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
        batch_op.add_column(
            sa.Column(
                "tds_payment_type",
                sa.String(length=40),
                nullable=False,
                server_default="none",
            )
        )
        batch_op.add_column(
            sa.Column("tds_rate_percent", sa.Numeric(6, 3), nullable=True)
        )
        batch_op.add_column(
            sa.Column("tds_threshold_amount", sa.Numeric(12, 2), nullable=True)
        )
        batch_op.add_column(sa.Column("tds_notes", sa.Text(), nullable=True))

    with op.batch_alter_table("purchase_orders", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "tds_applicable",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
        batch_op.add_column(sa.Column("tds_section", sa.String(length=20), nullable=True))
        batch_op.add_column(
            sa.Column(
                "tds_rate_percent",
                sa.Numeric(6, 3),
                nullable=False,
                server_default="0",
            )
        )
        batch_op.add_column(
            sa.Column(
                "tds_base_amount",
                sa.Numeric(12, 2),
                nullable=False,
                server_default="0",
            )
        )
        batch_op.add_column(
            sa.Column(
                "tds_amount",
                sa.Numeric(12, 2),
                nullable=False,
                server_default="0",
            )
        )
        batch_op.add_column(sa.Column("tds_reason", sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column("tds_deducted_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("tds_deposit_due_date", sa.Date(), nullable=True))
        batch_op.add_column(sa.Column("tds_deposited_at", sa.DateTime(), nullable=True))


def downgrade():
    with op.batch_alter_table("purchase_orders", schema=None) as batch_op:
        batch_op.drop_column("tds_deposited_at")
        batch_op.drop_column("tds_deposit_due_date")
        batch_op.drop_column("tds_deducted_at")
        batch_op.drop_column("tds_reason")
        batch_op.drop_column("tds_amount")
        batch_op.drop_column("tds_base_amount")
        batch_op.drop_column("tds_rate_percent")
        batch_op.drop_column("tds_section")
        batch_op.drop_column("tds_applicable")

    with op.batch_alter_table("vendors", schema=None) as batch_op:
        batch_op.drop_column("tds_notes")
        batch_op.drop_column("tds_threshold_amount")
        batch_op.drop_column("tds_rate_percent")
        batch_op.drop_column("tds_payment_type")
        batch_op.drop_column("tds_enabled")
        batch_op.drop_column("pan")
