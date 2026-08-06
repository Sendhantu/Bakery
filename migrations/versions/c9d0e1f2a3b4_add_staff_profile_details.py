"""Add staff profile details and locked staff emails.

Revision ID: c9d0e1f2a3b4
Revises: b8d2f4a6c9e1
Create Date: 2026-08-03 10:30:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "c9d0e1f2a3b4"
down_revision = "b8d2f4a6c9e1"
branch_labels = None
depends_on = None


STAFF_ROLES = (
    "super_admin",
    "admin",
    "branch_manager",
    "cashier",
    "kitchen_staff",
    "delivery",
)


def upgrade():
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.add_column(sa.Column("staff_address", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("date_of_joining", sa.Date(), nullable=True))
        batch_op.add_column(sa.Column("designation", sa.String(length=120), nullable=True))
        batch_op.add_column(sa.Column("emergency_contact", sa.String(length=50), nullable=True))
        batch_op.add_column(sa.Column("staff_notes", sa.Text(), nullable=True))
        batch_op.add_column(
            sa.Column(
                "email_locked",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )

    users = sa.table(
        "users",
        sa.column("role", sa.String()),
        sa.column("email_locked", sa.Boolean()),
    )
    op.execute(
        users.update()
        .where(users.c.role.in_(STAFF_ROLES))
        .values(email_locked=True)
    )

    if op.get_context().dialect.name != "sqlite":
        with op.batch_alter_table("users", schema=None) as batch_op:
            batch_op.alter_column("email_locked", server_default=None)


def downgrade():
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_column("email_locked")
        batch_op.drop_column("staff_notes")
        batch_op.drop_column("emergency_contact")
        batch_op.drop_column("designation")
        batch_op.drop_column("date_of_joining")
        batch_op.drop_column("staff_address")
