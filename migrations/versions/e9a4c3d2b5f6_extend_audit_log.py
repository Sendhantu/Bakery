"""extend_audit_log

Revision ID: e9a4c3d2b5f6
Revises: d8f3b2c1a4e5
Create Date: 2026-07-22 21:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "e9a4c3d2b5f6"
down_revision = "d8f3b2c1a4e5"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("audit_logs", sa.Column("before_value", sa.Text(), nullable=True))
    op.add_column("audit_logs", sa.Column("after_value", sa.Text(), nullable=True))
    op.add_column("audit_logs", sa.Column("ip_address", sa.String(length=64), nullable=True))
    op.create_index("idx_audit_action_created", "audit_logs", ["action", "created_at"])


def downgrade():
    op.drop_index("idx_audit_action_created", table_name="audit_logs")
    op.drop_column("audit_logs", "ip_address")
    op.drop_column("audit_logs", "after_value")
    op.drop_column("audit_logs", "before_value")
