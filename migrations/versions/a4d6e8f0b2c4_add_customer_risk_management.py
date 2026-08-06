"""Add customer risk management and fraud prevention.

Revision ID: a4d6e8f0b2c4
Revises: f4b5c6d7e8f9
Create Date: 2026-08-06 08:30:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "a4d6e8f0b2c4"
down_revision = "f4b5c6d7e8f9"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "customer_risk_profiles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("risk_status", sa.String(length=30), nullable=False),
        sa.Column("account_status", sa.String(length=30), nullable=False),
        sa.Column("case_owner_id", sa.Integer(), nullable=True),
        sa.Column("last_reviewed_at", sa.DateTime(), nullable=True),
        sa.Column("last_reviewed_by", sa.Integer(), nullable=True),
        sa.Column("review_due_at", sa.DateTime(), nullable=True),
        sa.Column("suspended_at", sa.DateTime(), nullable=True),
        sa.Column("suspended_by", sa.Integer(), nullable=True),
        sa.Column("suspension_reason", sa.Text(), nullable=True),
        sa.Column("suspended_until", sa.DateTime(), nullable=True),
        sa.Column("blocked_at", sa.DateTime(), nullable=True),
        sa.Column("blocked_by", sa.Integer(), nullable=True),
        sa.Column("block_reason", sa.Text(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.Column("deleted_by", sa.Integer(), nullable=True),
        sa.Column("deletion_reason", sa.Text(), nullable=True),
        sa.Column("anonymized_at", sa.DateTime(), nullable=True),
        sa.Column("anonymized_by", sa.Integer(), nullable=True),
        sa.Column("fraud_confirmed_at", sa.DateTime(), nullable=True),
        sa.Column("fraud_confirmed_by", sa.Integer(), nullable=True),
        sa.Column("session_revoked_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["case_owner_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["last_reviewed_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["suspended_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["blocked_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["deleted_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["anonymized_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["fraud_confirmed_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id"),
    )
    op.create_index(
        "idx_risk_profile_statuses",
        "customer_risk_profiles",
        ["risk_status", "account_status"],
    )

    op.create_table(
        "customer_restrictions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("restriction_type", sa.String(length=40), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("lifted_by", sa.Integer(), nullable=True),
        sa.Column("lifted_at", sa.DateTime(), nullable=True),
        sa.Column("lifted_reason", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["lifted_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_restriction_user_active",
        "customer_restrictions",
        ["user_id", "is_active"],
    )

    op.create_table(
        "customer_risk_actions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("admin_id", sa.Integer(), nullable=True),
        sa.Column("action_type", sa.String(length=40), nullable=False),
        sa.Column("previous_risk_status", sa.String(length=30), nullable=True),
        sa.Column("new_risk_status", sa.String(length=30), nullable=True),
        sa.Column("previous_account_status", sa.String(length=30), nullable=True),
        sa.Column("new_account_status", sa.String(length=30), nullable=True),
        sa.Column("reason_category", sa.String(length=60), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("evidence", sa.Text(), nullable=True),
        sa.Column("order_ids", sa.Text(), nullable=True),
        sa.Column("payment_refs", sa.Text(), nullable=True),
        sa.Column("ip_address", sa.String(length=60), nullable=True),
        sa.Column("approval_by", sa.Integer(), nullable=True),
        sa.Column("approval_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["admin_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["approval_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_risk_action_user_created",
        "customer_risk_actions",
        ["user_id", "created_at"],
    )
    op.create_index(
        "idx_risk_action_type_created",
        "customer_risk_actions",
        ["action_type", "created_at"],
    )

    op.create_table(
        "fraud_blocklist_entries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("identifier_type", sa.String(length=40), nullable=False),
        sa.Column("identifier_hash", sa.String(length=128), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("case_user_id", sa.Integer(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("reviewed_by", sa.Integer(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        sa.Column("review_notes", sa.Text(), nullable=True),
        sa.Column("match_count", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["case_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["reviewed_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "identifier_type", "identifier_hash", name="uq_blocklist_identifier"
        ),
    )


def downgrade():
    op.drop_table("fraud_blocklist_entries")
    op.drop_table("customer_risk_actions")
    op.drop_table("customer_restrictions")
    op.drop_table("customer_risk_profiles")
