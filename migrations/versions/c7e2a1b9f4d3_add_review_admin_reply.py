"""add_review_admin_reply

Revision ID: c7e2a1b9f4d3
Revises: b4c1f8d2a9e6
Create Date: 2026-07-22 19:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "c7e2a1b9f4d3"
down_revision = "b4c1f8d2a9e6"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("reviews", sa.Column("admin_reply", sa.Text(), nullable=True))
    op.add_column("reviews", sa.Column("admin_reply_at", sa.DateTime(), nullable=True))


def downgrade():
    op.drop_column("reviews", "admin_reply_at")
    op.drop_column("reviews", "admin_reply")
