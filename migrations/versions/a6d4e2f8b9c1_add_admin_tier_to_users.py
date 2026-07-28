"""add_admin_tier_to_users

Revision ID: a6d4e2f8b9c1
Revises: f2a7c9d1e3b4
Create Date: 2026-07-28 16:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "a6d4e2f8b9c1"
down_revision = "f2a7c9d1e3b4"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "users",
        sa.Column(
            "admin_tier",
            sa.String(length=20),
            nullable=False,
            server_default="owner",
        ),
    )
    op.create_index("idx_users_role_admin_tier", "users", ["role", "admin_tier"])
    op.execute("UPDATE users SET admin_tier = 'owner' WHERE role IN ('admin', 'super_admin')")
    op.execute("UPDATE users SET admin_tier = 'manager' WHERE role = 'branch_manager'")
    op.execute("UPDATE users SET admin_tier = 'staff' WHERE role IN ('cashier', 'kitchen_staff')")


def downgrade():
    op.drop_index("idx_users_role_admin_tier", table_name="users")
    op.drop_column("users", "admin_tier")
