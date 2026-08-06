"""add_category_images

Revision ID: a8c6d4e2f9b1
Revises: f5b8d6a4c3e2
Create Date: 2026-07-31 17:45:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "a8c6d4e2f9b1"
down_revision = "f5b8d6a4c3e2"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("categories", schema=None) as batch_op:
        batch_op.add_column(sa.Column("image", sa.String(length=512), nullable=True))
        batch_op.add_column(sa.Column("image_url", sa.String(length=512), nullable=True))


def downgrade():
    with op.batch_alter_table("categories", schema=None) as batch_op:
        batch_op.drop_column("image_url")
        batch_op.drop_column("image")
