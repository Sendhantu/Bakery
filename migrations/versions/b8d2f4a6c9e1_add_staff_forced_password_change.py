"""Add forced password-change flag for staff accounts.

Revision ID: b8d2f4a6c9e1
Revises: a9b1c3d4e5f6
Create Date: 2026-08-02 14:20:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "b8d2f4a6c9e1"
down_revision = "a9b1c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "users",
        sa.Column(
            "must_change_password",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column("users", sa.Column("password_changed_at", sa.DateTime(), nullable=True))
    if op.get_context().dialect.name != "sqlite":
        op.alter_column("users", "must_change_password", server_default=None)


def downgrade():
    op.drop_column("users", "password_changed_at")
    op.drop_column("users", "must_change_password")
