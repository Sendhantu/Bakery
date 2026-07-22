"""add_stock_movements

Revision ID: b4c1f8d2a9e6
Revises: 9f2b1a7c4e8d
Create Date: 2026-07-22 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "b4c1f8d2a9e6"
down_revision = "9f2b1a7c4e8d"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "stock_movements",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("raw_material_id", sa.Integer(), nullable=False),
        sa.Column("change_amount", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("stock_after", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("reason", sa.String(length=40), nullable=False),
        sa.Column("reference_order_id", sa.Integer(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["raw_material_id"], ["raw_materials.id"]),
        sa.ForeignKeyConstraint(["reference_order_id"], ["orders.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_stock_movement_material_created",
        "stock_movements",
        ["raw_material_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "idx_stock_movement_order",
        "stock_movements",
        ["reference_order_id"],
        unique=False,
    )
    op.create_index(
        "idx_stock_movement_reason",
        "stock_movements",
        ["reason"],
        unique=False,
    )


def downgrade():
    op.drop_index("idx_stock_movement_reason", table_name="stock_movements")
    op.drop_index("idx_stock_movement_order", table_name="stock_movements")
    op.drop_index("idx_stock_movement_material_created", table_name="stock_movements")
    op.drop_table("stock_movements")
