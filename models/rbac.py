"""Role-based access control (RBAC) models.

These tables implement the employee access-control system on top of the
existing `users` table. The `User.role` string column remains the employee's
base role slug (matches `roles.slug`) so existing role checks keep working,
while permissions are the actual source of authorization for RBAC-managed
employees (`User.rbac_enabled = True`).
"""

from clock import utcnow
from .base import db

EMPLOYEE_STATUSES = (
    "invited",
    "active",
    "inactive",
    "temporarily_suspended",
    "locked",
    "resigned",
    "terminated",
    "access_expired",
)
EMPLOYEE_STATUS_LABELS = {
    "invited": "Invited",
    "active": "Active",
    "inactive": "Inactive",
    "temporarily_suspended": "Temporarily Suspended",
    "locked": "Locked",
    "resigned": "Resigned",
    "terminated": "Terminated",
    "access_expired": "Access Expired",
}
EMPLOYEE_STATUSES_ACTIVE = {"active"}
EMPLOYEE_STATUSES_LOCKED = {
    "inactive",
    "temporarily_suspended",
    "locked",
    "resigned",
    "terminated",
    "access_expired",
}

EMPLOYMENT_STATUSES = ("full_time", "part_time", "contract", "probation", "intern")
EMPLOYMENT_STATUS_LABELS = {
    "full_time": "Full Time",
    "part_time": "Part Time",
    "contract": "Contract",
    "probation": "Probation",
    "intern": "Intern",
}

BRANCH_SCOPE_VALUES = ("all", "assigned", "department", "assigned_records", "own")
BRANCH_SCOPE_LABELS = {
    "all": "All branches",
    "assigned": "Assigned branches only",
    "department": "Department records",
    "assigned_records": "Assigned records only",
    "own": "Own records only",
}

OVERRIDE_DECISIONS = ("grant", "deny")
OVERRIDE_DECISION_LABELS = {"grant": "Granted", "deny": "Denied"}

APPROVAL_REQUEST_STATUSES = (
    "requested",
    "pending",
    "approved",
    "rejected",
    "completed",
    "cancelled",
    "expired",
)
APPROVAL_REQUEST_STATUS_LABELS = {
    "requested": "Requested",
    "pending": "Pending Approval",
    "approved": "Approved",
    "rejected": "Rejected",
    "completed": "Completed",
    "cancelled": "Cancelled",
    "expired": "Expired",
}


class Role(db.Model):
    __tablename__ = "roles"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), nullable=False, unique=True)
    slug = db.Column(db.String(80), nullable=False, unique=True)
    description = db.Column(db.Text)
    is_system = db.Column(db.Boolean, default=False, nullable=False)
    is_protected = db.Column(db.Boolean, default=False, nullable=False)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    permissions = db.relationship(
        "RolePermission",
        backref="role",
        lazy="dynamic",
        cascade="all, delete-orphan",
        foreign_keys="RolePermission.role_id",
    )
    creator = db.relationship("User", foreign_keys=[created_by])

    __table_args__ = (
        db.Index("idx_roles_system", "is_system"),
        db.Index("idx_roles_protected", "is_protected"),
    )

    def permission_keys(self):
        return {row.permission for row in self.permissions.all()}


class RolePermission(db.Model):
    __tablename__ = "role_permissions"
    id = db.Column(db.Integer, primary_key=True)
    role_id = db.Column(db.Integer, db.ForeignKey("roles.id"), nullable=False)
    permission = db.Column(db.String(120), nullable=False)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)

    __table_args__ = (
        db.UniqueConstraint("role_id", "permission", name="uq_role_permission"),
        db.Index("idx_role_permission_key", "permission"),
    )


class EmployeePermissionOverride(db.Model):
    __tablename__ = "employee_permission_overrides"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    permission = db.Column(db.String(120), nullable=False)
    decision = db.Column(db.String(10), nullable=False, default="grant")
    granted_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    reason = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)

    user = db.relationship("User", foreign_keys=[user_id], backref="permission_overrides")
    granted_by_user = db.relationship("User", foreign_keys=[granted_by])

    __table_args__ = (
        db.UniqueConstraint(
            "user_id",
            "permission",
            "decision",
            name="uq_employee_permission_override",
        ),
        db.Index("idx_override_user_permission", "user_id", "permission"),
    )


class EmployeeBranch(db.Model):
    __tablename__ = "employee_branches"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)

    user = db.relationship("User", foreign_keys=[user_id], backref="employee_branches")
    branch = db.relationship("Branch")

    __table_args__ = (
        db.UniqueConstraint("user_id", "branch_id", name="uq_employee_branch"),
        db.Index("idx_employee_branch", "branch_id"),
    )


class TemporaryPermission(db.Model):
    __tablename__ = "temporary_permissions"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    permission = db.Column(db.String(120), nullable=False)
    starts_at = db.Column(db.DateTime, nullable=False)
    ends_at = db.Column(db.DateTime, nullable=False)
    granted_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    reason = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)

    user = db.relationship(
        "User", foreign_keys=[user_id], backref="temporary_permissions"
    )
    granted_by_user = db.relationship("User", foreign_keys=[granted_by])

    __table_args__ = (
        db.Index("idx_temp_permission_user_active", "user_id", "ends_at"),
        db.Index("idx_temp_permission_key", "permission"),
    )


class UserSession(db.Model):
    __tablename__ = "user_sessions"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    token_hash = db.Column(db.String(64), nullable=False)
    ip_address = db.Column(db.String(64))
    user_agent = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)
    last_seen_at = db.Column(db.DateTime, default=utcnow, nullable=False)
    revoked_at = db.Column(db.DateTime)

    user = db.relationship("User", foreign_keys=[user_id], backref="user_sessions")

    __table_args__ = (
        db.Index("idx_user_session_active", "user_id", "revoked_at"),
        db.Index("idx_user_session_token", "token_hash"),
    )


class ApprovalWorkflow(db.Model):
    __tablename__ = "approval_workflows"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    module = db.Column(db.String(60), nullable=False)
    action = db.Column(db.String(120), nullable=False)
    permission = db.Column(db.String(120), nullable=False)
    threshold = db.Column(db.Numeric(14, 2), default=0, nullable=False)
    required_role = db.Column(db.String(80))
    num_approvers = db.Column(db.Integer, default=1, nullable=False)
    allowed_branches = db.Column(db.Text)
    expiry_minutes = db.Column(db.Integer, default=1440, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    __table_args__ = (
        db.UniqueConstraint("module", "action", name="uq_approval_workflow_scope"),
        db.Index("idx_approval_workflow_active", "is_active"),
    )


class ApprovalRequest(db.Model):
    __tablename__ = "approval_requests"
    id = db.Column(db.Integer, primary_key=True)
    workflow_id = db.Column(db.Integer, db.ForeignKey("approval_workflows.id"))
    requester_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    module = db.Column(db.String(60), nullable=False)
    action = db.Column(db.String(120), nullable=False)
    permission = db.Column(db.String(120), nullable=False)
    target_type = db.Column(db.String(80))
    target_id = db.Column(db.String(80))
    amount = db.Column(db.Numeric(14, 2), default=0)
    payload_json = db.Column(db.Text)
    status = db.Column(db.String(20), default="requested", nullable=False)
    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"))
    expires_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)
    resolved_at = db.Column(db.DateTime)

    workflow = db.relationship("ApprovalWorkflow")
    requester = db.relationship("User", foreign_keys=[requester_id])
    branch = db.relationship("Branch")
    votes = db.relationship(
        "ApprovalVote",
        backref="approval_request",
        lazy="dynamic",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        db.Index("idx_approval_request_status_created", "status", "created_at"),
        db.Index("idx_approval_request_requester", "requester_id"),
    )


class ApprovalVote(db.Model):
    __tablename__ = "approval_votes"
    id = db.Column(db.Integer, primary_key=True)
    approval_request_id = db.Column(
        db.Integer, db.ForeignKey("approval_requests.id"), nullable=False
    )
    approver_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    decision = db.Column(db.String(10), nullable=False)
    reason = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)

    approver = db.relationship("User", foreign_keys=[approver_id])

    __table_args__ = (
        db.UniqueConstraint(
            "approval_request_id",
            "approver_id",
            name="uq_approval_vote_approver",
        ),
    )
