"""Backfill and enforce unique staff employee IDs.

Revision ID: c4e7a1b9d2f6
Revises: b2d6f8a1c3e5
Create Date: 2026-08-21 10:05:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "c4e7a1b9d2f6"
down_revision = "b2d6f8a1c3e5"
branch_labels = None
depends_on = None


STAFF_ROLES = (
    "super_admin",
    "admin",
    "branch_manager",
    "branch_staff",
    "cashier",
    "kitchen_staff",
)


def upgrade():
    connection = op.get_bind()
    staff_rows = connection.execute(
        sa.text(
            "SELECT id FROM users "
            "WHERE role IN (:super_admin, :admin, :branch_manager, :branch_staff, :cashier, :kitchen_staff) "
            "AND (employee_id IS NULL OR employee_id = '')"
        ),
        {
            "super_admin": "super_admin",
            "admin": "admin",
            "branch_manager": "branch_manager",
            "branch_staff": "branch_staff",
            "cashier": "cashier",
            "kitchen_staff": "kitchen_staff",
        },
    ).fetchall()

    for row in staff_rows:
        user_id = int(row[0])
        connection.execute(
            sa.text("UPDATE users SET employee_id = :employee_id WHERE id = :user_id"),
            {
                "employee_id": f"SC-STF-{user_id:06d}",
                "user_id": user_id,
            },
        )

    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_index("ix_users_employee_id")
        batch_op.create_index(
            "ix_users_employee_id",
            ["employee_id"],
            unique=True,
        )


def downgrade():
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_index("ix_users_employee_id")
        batch_op.create_index(
            "ix_users_employee_id",
            ["employee_id"],
            unique=False,
        )
