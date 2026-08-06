"""Add product special ingredient field.

Revision ID: f4b5c6d7e8f9
Revises: f3a4b5c6d7e8
Create Date: 2026-08-04 10:30:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "f4b5c6d7e8f9"
down_revision = "f3a4b5c6d7e8"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("products", schema=None) as batch_op:
        batch_op.add_column(sa.Column("special_ingredient", sa.String(length=255)))


def downgrade():
    with op.batch_alter_table("products", schema=None) as batch_op:
        batch_op.drop_column("special_ingredient")
