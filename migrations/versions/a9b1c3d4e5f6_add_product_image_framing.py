"""add product image framing

Revision ID: a9b1c3d4e5f6
Revises: f7a8b9c0d1e2
Create Date: 2026-08-02 14:05:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "a9b1c3d4e5f6"
down_revision = "f7a8b9c0d1e2"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("products", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "image_fit",
                sa.String(length=20),
                nullable=True,
                server_default="cover",
            )
        )
        batch_op.add_column(
            sa.Column(
                "image_position",
                sa.String(length=20),
                nullable=True,
                server_default="center",
            )
        )


def downgrade():
    with op.batch_alter_table("products", schema=None) as batch_op:
        batch_op.drop_column("image_position")
        batch_op.drop_column("image_fit")
