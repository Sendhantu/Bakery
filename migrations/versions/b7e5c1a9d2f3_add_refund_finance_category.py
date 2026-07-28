"""add_refund_finance_category

Revision ID: b7e5c1a9d2f3
Revises: a6d4e2f8b9c1
Create Date: 2026-07-28 16:45:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "b7e5c1a9d2f3"
down_revision = "a6d4e2f8b9c1"
branch_labels = None
depends_on = None


def upgrade():
    categories = sa.table(
        "financial_categories",
        sa.column("code", sa.String),
        sa.column("label", sa.String),
        sa.column("transaction_type", sa.String),
        sa.column("is_system", sa.Boolean),
        sa.column("is_active", sa.Boolean),
        sa.column("sort_order", sa.Integer),
    )
    bind = op.get_bind()
    existing = bind.execute(
        sa.select(categories.c.code).where(categories.c.code == "refund")
    ).first()
    if existing is None:
        bind.execute(
            categories.insert().values(
                code="refund",
                label="Refunds",
                transaction_type="expense",
                is_system=True,
                is_active=True,
                sort_order=65,
            )
        )


def downgrade():
    categories = sa.table(
        "financial_categories",
        sa.column("code", sa.String),
    )
    op.execute(categories.delete().where(categories.c.code == "refund"))
