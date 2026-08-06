"""add rbac tables and employee fields

Revision ID: d7e8f9a0b1c2
Revises: c3e5a7b9d1f3
Create Date: 2026-08-06 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "d7e8f9a0b1c2"
down_revision = "c3e5a7b9d1f3"
branch_labels = None
depends_on = None


def upgrade():
    # Employee / RBAC fields on users
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(sa.Column("rbac_enabled", sa.Boolean(), nullable=False, server_default=sa.text("0")))
        batch_op.add_column(sa.Column("employee_status", sa.String(length=30), nullable=False, server_default="active"))
        batch_op.add_column(sa.Column("employment_status", sa.String(length=30)))
        batch_op.add_column(sa.Column("employee_id", sa.String(length=40)))
        batch_op.add_column(sa.Column("department", sa.String(length=80)))
        batch_op.add_column(sa.Column("job_title", sa.String(length=120)))
        batch_op.add_column(sa.Column("invite_token", sa.String(length=64)))
        batch_op.add_column(sa.Column("invite_token_expires_at", sa.DateTime()))
        batch_op.add_column(sa.Column("invited_at", sa.DateTime()))
        batch_op.add_column(sa.Column("invite_accepted_at", sa.DateTime()))
        batch_op.add_column(sa.Column("force_logout_before", sa.DateTime()))
        batch_op.add_column(sa.Column("branch_scope", sa.String(length=20), nullable=False, server_default="all"))
        batch_op.add_column(sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id")))
        batch_op.add_column(sa.Column("last_login_at", sa.DateTime()))
        batch_op.create_index("ix_users_employee_id", ["employee_id"])
        batch_op.create_index("ix_users_invite_token", ["invite_token"])

    # Roles
    op.create_table(
        "roles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("slug", sa.String(length=80), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("is_system", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("is_protected", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("name", name="uq_roles_name"),
        sa.UniqueConstraint("slug", name="uq_roles_slug"),
    )
    op.create_index("idx_roles_system", "roles", ["is_system"])
    op.create_index("idx_roles_protected", "roles", ["is_protected"])

    # Role <-> permission mapping
    op.create_table(
        "role_permissions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("role_id", sa.Integer(), sa.ForeignKey("roles.id"), nullable=False),
        sa.Column("permission", sa.String(length=120), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("role_id", "permission", name="uq_role_permission"),
    )
    op.create_index("idx_role_permission_key", "role_permissions", ["permission"])

    # Per-employee permission overrides (grant / deny)
    op.create_table(
        "employee_permission_overrides",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("permission", sa.String(length=120), nullable=False),
        sa.Column("decision", sa.String(length=10), nullable=False, server_default="grant"),
        sa.Column("granted_by", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("reason", sa.Text()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("user_id", "permission", "decision", name="uq_employee_permission_override"),
    )
    op.create_index("idx_override_user_permission", "employee_permission_overrides", ["user_id", "permission"])

    # Branch assignment for employees
    op.create_table(
        "employee_branches",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("branch_id", sa.Integer(), sa.ForeignKey("branches.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("user_id", "branch_id", name="uq_employee_branch"),
    )
    op.create_index("idx_employee_branch", "employee_branches", ["branch_id"])

    # Temporary permissions
    op.create_table(
        "temporary_permissions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("permission", sa.String(length=120), nullable=False),
        sa.Column("starts_at", sa.DateTime(), nullable=False),
        sa.Column("ends_at", sa.DateTime(), nullable=False),
        sa.Column("granted_by", sa.Integer(), sa.ForeignKey("users.id")),
        sa.Column("reason", sa.Text()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("idx_temp_permission_user_active", "temporary_permissions", ["user_id", "ends_at"])
    op.create_index("idx_temp_permission_key", "temporary_permissions", ["permission"])

    # Server-side session tracking (for revocation + active-session list)
    op.create_table(
        "user_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("ip_address", sa.String(length=64)),
        sa.Column("user_agent", sa.String(length=255)),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("revoked_at", sa.DateTime()),
    )
    op.create_index("idx_user_session_active", "user_sessions", ["user_id", "revoked_at"])
    op.create_index("idx_user_session_token", "user_sessions", ["token_hash"])

    # Approval workflows
    op.create_table(
        "approval_workflows",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("module", sa.String(length=60), nullable=False),
        sa.Column("action", sa.String(length=120), nullable=False),
        sa.Column("permission", sa.String(length=120), nullable=False),
        sa.Column("threshold", sa.Numeric(14, 2), nullable=False, server_default=sa.text("0")),
        sa.Column("required_role", sa.String(length=80)),
        sa.Column("num_approvers", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("allowed_branches", sa.Text()),
        sa.Column("expiry_minutes", sa.Integer(), nullable=False, server_default=sa.text("1440")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("module", "action", name="uq_approval_workflow_scope"),
    )
    op.create_index("idx_approval_workflow_active", "approval_workflows", ["is_active"])

    # Approval requests
    op.create_table(
        "approval_requests",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("workflow_id", sa.Integer(), sa.ForeignKey("approval_workflows.id")),
        sa.Column("requester_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("module", sa.String(length=60), nullable=False),
        sa.Column("action", sa.String(length=120), nullable=False),
        sa.Column("permission", sa.String(length=120), nullable=False),
        sa.Column("target_type", sa.String(length=80)),
        sa.Column("target_id", sa.String(length=80)),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False, server_default=sa.text("0")),
        sa.Column("payload_json", sa.Text()),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="requested"),
        sa.Column("branch_id", sa.Integer(), sa.ForeignKey("branches.id")),
        sa.Column("expires_at", sa.DateTime()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("resolved_at", sa.DateTime()),
    )
    op.create_index("idx_approval_request_status_created", "approval_requests", ["status", "created_at"])
    op.create_index("idx_approval_request_requester", "approval_requests", ["requester_id"])

    # Approval votes
    op.create_table(
        "approval_votes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("approval_request_id", sa.Integer(), sa.ForeignKey("approval_requests.id"), nullable=False),
        sa.Column("approver_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("decision", sa.String(length=10), nullable=False),
        sa.Column("reason", sa.Text()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("approval_request_id", "approver_id", name="uq_approval_vote_approver"),
    )


def downgrade():
    op.drop_table("approval_votes")
    op.drop_table("approval_requests")
    op.drop_table("approval_workflows")
    op.drop_table("user_sessions")
    op.drop_table("temporary_permissions")
    op.drop_table("employee_branches")
    op.drop_table("employee_permission_overrides")
    op.drop_table("role_permissions")
    op.drop_table("roles")

    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_index("ix_users_employee_id")
        batch_op.drop_index("ix_users_invite_token")
        batch_op.drop_column("created_by_id")
        batch_op.drop_column("last_login_at")
        batch_op.drop_column("branch_scope")
        batch_op.drop_column("force_logout_before")
        batch_op.drop_column("invite_accepted_at")
        batch_op.drop_column("invited_at")
        batch_op.drop_column("invite_token_expires_at")
        batch_op.drop_column("invite_token")
        batch_op.drop_column("job_title")
        batch_op.drop_column("department")
        batch_op.drop_column("employee_id")
        batch_op.drop_column("employment_status")
        batch_op.drop_column("employee_status")
        batch_op.drop_column("rbac_enabled")
