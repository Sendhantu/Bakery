"""Add auditor requirement workflow.

Revision ID: b2d6f8a1c3e5
Revises: a9c1d4e7b8f2
Create Date: 2026-08-13 14:30:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "b2d6f8a1c3e5"
down_revision = "a9c1d4e7b8f2"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "auditor_requirements",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("requirement_uid", sa.String(length=40), nullable=False),
        sa.Column("auditor_id", sa.Integer(), nullable=False),
        sa.Column("financial_year", sa.String(length=20), nullable=False),
        sa.Column("period_label", sa.String(length=80), nullable=True),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("category", sa.String(length=50), nullable=False, server_default="Other"),
        sa.Column("priority", sa.String(length=20), nullable=False, server_default="NORMAL"),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="OPEN"),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("requested_at", sa.DateTime(), nullable=False),
        sa.Column("requested_by", sa.Integer(), nullable=False),
        sa.Column("assigned_to", sa.Integer(), nullable=True),
        sa.Column("admin_response", sa.Text(), nullable=True),
        sa.Column("latest_auditor_comment", sa.Text(), nullable=True),
        sa.Column("submitted_at", sa.DateTime(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["assigned_to"], ["users.id"]),
        sa.ForeignKeyConstraint(["auditor_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["requested_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("requirement_uid"),
    )
    op.create_index(
        "idx_auditor_requirement_status_year",
        "auditor_requirements",
        ["status", "financial_year"],
    )
    op.create_index(
        "idx_auditor_requirement_auditor_status",
        "auditor_requirements",
        ["auditor_id", "status"],
    )
    op.create_index(
        "idx_auditor_requirement_category_status",
        "auditor_requirements",
        ["category", "status"],
    )
    op.create_index(
        "idx_auditor_requirement_due_date",
        "auditor_requirements",
        ["due_date"],
    )

    with op.batch_alter_table("audit_documents") as batch_op:
        batch_op.add_column(sa.Column("requirement_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("period_label", sa.String(length=80), nullable=True))
        batch_op.add_column(sa.Column("document_type", sa.String(length=80), nullable=True))
        batch_op.add_column(sa.Column("description", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("document_date", sa.Date(), nullable=True))
        batch_op.add_column(sa.Column("archived_at", sa.DateTime(), nullable=True))
        batch_op.create_foreign_key(
            "fk_audit_documents_requirement",
            "auditor_requirements",
            ["requirement_id"],
            ["id"],
        )
        batch_op.create_index(
            "idx_audit_document_requirement_status",
            ["requirement_id", "status"],
        )

    op.create_table(
        "auditor_requirement_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("requirement_id", sa.Integer(), nullable=False),
        sa.Column("actor_id", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=50), nullable=False),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("document_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["document_id"], ["audit_documents.id"]),
        sa.ForeignKeyConstraint(["requirement_id"], ["auditor_requirements.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_audit_requirement_event_requirement_created",
        "auditor_requirement_events",
        ["requirement_id", "created_at"],
    )


def downgrade():
    op.drop_index(
        "idx_audit_requirement_event_requirement_created",
        table_name="auditor_requirement_events",
    )
    op.drop_table("auditor_requirement_events")

    with op.batch_alter_table("audit_documents") as batch_op:
        batch_op.drop_index("idx_audit_document_requirement_status")
        batch_op.drop_constraint("fk_audit_documents_requirement", type_="foreignkey")
        batch_op.drop_column("archived_at")
        batch_op.drop_column("document_date")
        batch_op.drop_column("description")
        batch_op.drop_column("document_type")
        batch_op.drop_column("period_label")
        batch_op.drop_column("requirement_id")

    op.drop_index("idx_auditor_requirement_due_date", table_name="auditor_requirements")
    op.drop_index(
        "idx_auditor_requirement_category_status",
        table_name="auditor_requirements",
    )
    op.drop_index(
        "idx_auditor_requirement_auditor_status",
        table_name="auditor_requirements",
    )
    op.drop_index(
        "idx_auditor_requirement_status_year",
        table_name="auditor_requirements",
    )
    op.drop_table("auditor_requirements")
