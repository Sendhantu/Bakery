"""RBAC service — effective permissions, overrides, branches, sessions,
masking, super-admin protection and approval workflows.

Permission resolution priority (per spec):
  1. Super Admin protection rules (bypass)
  2. Explicit employee deny
  3. Explicit employee grant / temporary permission
  4. Role permission
  5. Default deny
"""

from __future__ import annotations

import hashlib
import json
import secrets
from decimal import Decimal

from flask import g, has_request_context, request

from clock import utcnow
from models import (
    ApprovalRequest,
    ApprovalVote,
    ApprovalWorkflow,
    EmployeeBranch,
    EmployeePermissionOverride,
    Role,
    RolePermission,
    TemporaryPermission,
    User,
    UserSession,
    db,
)
from services.rbac_catalog import (
    ALL_PERMISSION_KEYS,
    APPROVAL_GATED_PERMISSIONS,
    DEFAULT_ROLE_PERMISSIONS,
    DEFAULT_ROLE_META,
    FIELD_ACCESS_KEYS,
    MODULE_LABELS,
    MODULE_BY_PERMISSION,
    PERMISSION_LABELS,
    PROTECTED_ROLE_SLUGS,
    SENSITIVE_PERMISSIONS,
    SUPER_ADMIN_ROLE_SLUG,
    valid_permission,
)

OVERRIDE_GRANT = "grant"
OVERRIDE_DENY = "deny"


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _client_ip() -> str:
    if not has_request_context():
        return ""
    forwarded = (request.headers.get("X-Forwarded-For") or "").split(",")[0].strip()
    return forwarded or (request.remote_addr or "")


def _user_agent() -> str:
    if not has_request_context():
        return ""
    return (request.user_agent.string or "")[:255]


class RbacService:
    # ── Role management ────────────────────────────────────────
    def ensure_default_roles(self, commit=True):
        for slug, permissions in DEFAULT_ROLE_PERMISSIONS.items():
            meta = DEFAULT_ROLE_META.get(slug, {})
            role = Role.query.filter_by(slug=slug).first()
            if role is None:
                role = Role(
                    name=meta.get("name", slug.replace("_", " ").title()),
                    slug=slug,
                    description=meta.get("description", ""),
                    is_system=True,
                    is_protected=bool(meta.get("protected", False)),
                )
                db.session.add(role)
                db.session.flush()
            else:
                role.name = meta.get("name", role.name)
                role.is_protected = bool(meta.get("protected", role.is_protected))
            self._set_role_permission_keys(role, permissions)
        if commit:
            db.session.commit()

    def _set_role_permission_keys(self, role, keys):
        existing = {row.permission for row in role.permissions.all()}
        for key in keys:
            if key not in existing:
                db.session.add(RolePermission(role_id=role.id, permission=key))
        for row in role.permissions.all():
            if row.permission not in keys:
                db.session.delete(row)

    def list_roles(self):
        return Role.query.order_by(Role.is_system.desc(), Role.name.asc()).all()

    def get_role(self, slug):
        return Role.query.filter_by(slug=slug).first()

    def get_role_by_id(self, role_id):
        return db.session.get(Role, role_id)

    def get_role_for_user(self, user):
        if user is None:
            return None
        return self.get_role((user.role or "").strip().lower())

    def create_custom_role(self, *, name, slug, description, permission_keys, actor, reason=""):
        name = (name or "").strip()
        slug = ((slug or name or "").strip().lower().replace(" ", "_")).strip("_")
        if not name or not slug:
            raise ValueError("Role name is required.")
        if Role.query.filter_by(slug=slug).first():
            raise ValueError("A role with that key already exists.")
        if slug in PROTECTED_ROLE_SLUGS or slug in DEFAULT_ROLE_META:
            raise ValueError("That role key is reserved for a default role.")
        role = Role(
            name=name,
            slug=slug,
            description=description or "",
            is_system=False,
            is_protected=False,
            created_by=getattr(actor, "id", None),
        )
        db.session.add(role)
        db.session.flush()
        valid_keys = {k for k in permission_keys if valid_permission(k)}
        self._set_role_permission_keys(role, valid_keys)
        db.session.flush()
        self._audit(
            actor,
            "role_created",
            role,
            before=None,
            after={"name": role.name, "slug": role.slug, "permissions": sorted(valid_keys)},
            change_summary=f"Custom role {role.name} created.",
            metadata={"reason": reason},
        )
        return role

    def update_role_permissions(self, role, permission_keys, *, actor, reason=""):
        if role.is_protected and not self.is_super_admin(actor):
            raise PermissionError("Only a Super Admin can change a protected role.")
        before = sorted(role.permission_keys())
        valid_keys = {k for k in permission_keys if valid_permission(k)}
        self._set_role_permission_keys(role, valid_keys)
        db.session.flush()
        added = sorted(valid_keys - set(before))
        removed = sorted(set(before) - valid_keys)
        self._audit(
            actor,
            "role_permissions_changed",
            role,
            before={"permissions": before},
            after={"permissions": sorted(valid_keys)},
            change_summary=f"Permissions changed for role {role.name}.",
            metadata={"added": added, "removed": removed, "reason": reason},
        )
        return {"added": added, "removed": removed}

    def reset_role_to_defaults(self, role, *, actor):
        if role.slug not in DEFAULT_ROLE_PERMISSIONS:
            raise ValueError("Only default roles have built-in defaults.")
        before = sorted(role.permission_keys())
        defaults = set(DEFAULT_ROLE_PERMISSIONS[role.slug])
        self._set_role_permission_keys(role, defaults)
        db.session.flush()
        self._audit(
            actor,
            "role_reset_to_defaults",
            role,
            before={"permissions": before},
            after={"permissions": sorted(defaults)},
            change_summary=f"Role {role.name} reset to defaults.",
        )
        return defaults

    def copy_role_permissions(self, target_role, source_role, *, actor):
        if target_role.is_protected and not self.is_super_admin(actor):
            raise PermissionError("Only a Super Admin can change a protected role.")
        before = sorted(target_role.permission_keys())
        source_keys = set(source_role.permission_keys())
        self._set_role_permission_keys(target_role, source_keys)
        db.session.flush()
        self._audit(
            actor,
            "role_permissions_copied",
            target_role,
            before={"permissions": before},
            after={"permissions": sorted(source_keys)},
            change_summary=(
                f"Permissions copied from {source_role.name} to {target_role.name}."
            ),
        )
        return sorted(source_keys)

    def delete_custom_role(self, role, *, actor):
        if role.is_system or role.is_protected:
            raise ValueError("System and protected roles cannot be deleted.")
        users = User.query.filter_by(role=role.slug).count()
        if users:
            raise ValueError(
                f"Role {role.name} is assigned to {users} employee(s); reassign them first."
            )
        self._audit(
            actor,
            "role_deleted",
            role,
            before={"name": role.name, "permissions": sorted(role.permission_keys())},
            change_summary=f"Custom role {role.name} deleted.",
        )
        db.session.delete(role)

    # ── Identity helpers ───────────────────────────────────────
    def is_rbac_managed(self, user) -> bool:
        return bool(getattr(user, "rbac_enabled", False))

    def is_super_admin(self, user) -> bool:
        if user is None:
            return False
        role = (getattr(user, "role", "") or "").strip().lower()
        if role == SUPER_ADMIN_ROLE_SLUG:
            return True
        if role == "admin" and self.is_rbac_managed(user):
            return True
        return False

    def is_protected_admin(self, user) -> bool:
        """Accounts that the RBAC layer refuses to weaken past the last one."""
        if user is None:
            return False
        if not self.is_rbac_managed(user):
            from utils.permissions import admin_tier_meets

            return admin_tier_meets(user, "owner")
        return (user.role or "").strip().lower() in {"admin", "super_admin"}

    # ── Permission resolution ──────────────────────────────────
    def _role_permission_keys_for_user(self, user) -> set:
        role = self.get_role_for_user(user)
        if role is not None:
            return role.permission_keys()
        return set(DEFAULT_ROLE_PERMISSIONS.get((user.role or "").strip().lower(), set()))

    def _active_temporary_keys(self, user, now) -> set:
        return {
            row.permission
            for row in TemporaryPermission.query.filter_by(user_id=user.id).all()
            if row.starts_at <= now <= row.ends_at
        }

    def _clear_cache(self, user=None):
        cache = getattr(g, "rbac_permissions_cache", None)
        if cache is not None:
            if user is not None:
                cache.pop(user.id, None)
            else:
                cache.clear()

    def effective_permissions(self, user, now=None):
        """Return {permission: bool} for the employee."""
        if user is None or not getattr(user, "is_authenticated", False):
            return {}
        if self.is_super_admin(user):
            return {key: True for key in ALL_PERMISSION_KEYS}
        if not self.is_rbac_managed(user):
            return {}
        cache = getattr(g, "rbac_permissions_cache", None)
        if cache is None:
            cache = {}
            g.rbac_permissions_cache = cache
        cached = cache.get(user.id)
        if cached is not None:
            return cached
        now = now or utcnow()
        role_keys = self._role_permission_keys_for_user(user)
        grants = {
            row.permission
            for row in EmployeePermissionOverride.query.filter_by(
                user_id=user.id, decision=OVERRIDE_GRANT
            ).all()
        }
        denies = {
            row.permission
            for row in EmployeePermissionOverride.query.filter_by(
                user_id=user.id, decision=OVERRIDE_DENY
            ).all()
        }
        temps = self._active_temporary_keys(user, now)
        result = {}
        for key in ALL_PERMISSION_KEYS:
            if key in denies:
                result[key] = False
            elif key in grants:
                result[key] = True
            elif key in temps:
                result[key] = True
            elif key in role_keys:
                result[key] = True
            else:
                result[key] = False
        cache[user.id] = result
        return result

    def can(self, user, permission, now=None) -> bool:
        if not user or not getattr(user, "is_authenticated", False):
            return False
        if not self.is_rbac_managed(user):
            return True
        if not valid_permission(permission):
            return False
        return bool(self.effective_permissions(user, now=now).get(permission, False))

    def can_any(self, user, *permissions, now=None) -> bool:
        return any(self.can(user, perm, now=now) for perm in permissions)

    def requires(self, user, *permissions, now=None):
        """Raise PermissionError unless the user holds every listed permission."""
        for perm in permissions:
            if not self.can(user, perm, now=now):
                raise PermissionError(f"Permission denied: {perm}")

    def module_view_permission(self, module):
        return f"{module}.view"

    # ── Individual overrides ───────────────────────────────────
    def grant_permission(self, user, permission, *, actor, reason=""):
        if not valid_permission(permission):
            raise ValueError(f"Unknown permission: {permission}")
        self._authorize_grant(actor, permission)
        self._clear_cache(user)
        existing = EmployeePermissionOverride.query.filter_by(
            user_id=user.id, permission=permission, decision=OVERRIDE_GRANT
        ).first()
        if existing is None:
            db.session.add(
                EmployeePermissionOverride(
                    user_id=user.id,
                    permission=permission,
                    decision=OVERRIDE_GRANT,
                    granted_by=getattr(actor, "id", None),
                    reason=reason,
                )
            )
        self._audit(
            actor,
            "employee_permission_granted",
            user,
            before={"permission": permission, "granted": False},
            after={"permission": permission, "granted": True},
            change_summary=f"Granted {permission} to {user.name}.",
            metadata={"reason": reason},
        )

    def deny_permission(self, user, permission, *, actor, reason=""):
        if not valid_permission(permission):
            raise ValueError(f"Unknown permission: {permission}")
        self._authorize_grant(actor, permission)
        self._clear_cache(user)
        existing = EmployeePermissionOverride.query.filter_by(
            user_id=user.id, permission=permission, decision=OVERRIDE_DENY
        ).first()
        if existing is None:
            db.session.add(
                EmployeePermissionOverride(
                    user_id=user.id,
                    permission=permission,
                    decision=OVERRIDE_DENY,
                    granted_by=getattr(actor, "id", None),
                    reason=reason,
                )
            )
        self._audit(
            actor,
            "employee_permission_denied",
            user,
            before={"permission": permission, "denied": False},
            after={"permission": permission, "denied": True},
            change_summary=f"Denied {permission} for {user.name}.",
            metadata={"reason": reason},
        )

    def remove_override(self, user, permission, *, actor, reason=""):
        self._clear_cache(user)
        removed = (
            EmployeePermissionOverride.query.filter_by(
                user_id=user.id, permission=permission
            ).delete()
        )
        if removed:
            self._audit(
                actor,
                "employee_permission_override_removed",
                user,
                before={"permission": permission},
                after={"permission": permission, "override_removed": True},
                change_summary=f"Removed override for {permission} on {user.name}.",
                metadata={"reason": reason},
            )

    def override_entries(self, user):
        return (
            EmployeePermissionOverride.query.filter_by(user_id=user.id)
            .order_by(EmployeePermissionOverride.created_at.desc())
            .all()
        )

    def _authorize_grant(self, actor, permission):
        """An admin may not grant a permission they do not possess themselves."""
        if actor is None:
            raise PermissionError("Authentication required.")
        if self.is_super_admin(actor):
            return
        if not self.can(actor, permission):
            raise PermissionError(
                "You cannot grant a permission you do not have yourself."
            )

    # ── Role assignment ────────────────────────────────────────
    def assign_role(self, user, role_slug, *, actor, reason=""):
        role = self.get_role(role_slug)
        if role is None:
            raise ValueError("Unknown role.")
        self._guard_role_change(user, actor, role_slug)
        before = {"role": user.role}
        user.role = role.slug
        user.admin_tier = self._tier_for_role(role.slug, user.admin_tier)
        db.session.flush()
        self._clear_cache(user)
        self._audit(
            actor,
            "employee_role_changed",
            user,
            before=before,
            after={"role": user.role},
            change_summary=f"Role changed from {before['role']} to {user.role}.",
            metadata={"reason": reason, "new_role": role.name},
        )
        return role

    def _tier_for_role(self, role_slug, fallback_tier):
        mapping = {
            "super_admin": "owner",
            "admin": "owner",
            "branch_manager": "manager",
            "cashier": "staff",
            "kitchen_staff": "staff",
        }
        return mapping.get(role_slug, fallback_tier)

    def _guard_role_change(self, user, actor, new_role_slug):
        if actor is None or not getattr(actor, "is_authenticated", False):
            raise PermissionError("Authentication required.")
        if user.id == actor.id:
            raise PermissionError("Employees cannot change their own role.")
        if self.is_protected_admin(user) and not self.is_super_admin(actor):
            raise PermissionError("You cannot change the role of a protected admin.")
        if self.is_protected_admin(user):
            self._require_other_role_manager(actor, user)
        if new_role_slug == SUPER_ADMIN_ROLE_SLUG and not self.is_super_admin(actor):
            raise PermissionError("Only a Super Admin can grant the Super Admin role.")

    def _require_other_role_manager(self, actor, target):
        """Ensure at least one other protected admin with role-management remains."""
        if not self.is_protected_admin(target):
            return
        current = self.count_role_managers()
        still = self.count_role_managers(exclude=target.id)
        if current <= 1 or still == 0:
            raise PermissionError(
                "This is the last protected admin with access management; "
                "assign another one first."
            )

    def count_role_managers(self, exclude=None):
        count = 0
        for user in User.query.filter(User.is_active.is_(True)).all():
            if exclude is not None and user.id == exclude:
                continue
            if self.is_protected_admin(user):
                if self.is_rbac_managed(user):
                    if self.can(user, "settings.manage_roles"):
                        count += 1
                else:
                    count += 1
        return count

    def can_manage(self, actor, target, action="manage"):
        """Privilege-escalation guard used before employee access mutations."""
        if actor is None or not getattr(actor, "is_authenticated", False):
            raise PermissionError("Authentication required.")
        if target.id == actor.id and action in {"role", "permission", "status"}:
            raise PermissionError("You cannot modify your own access.")
        if self.is_protected_admin(target) and not self.is_super_admin(actor):
            raise PermissionError("You cannot manage a protected admin account.")
        if self.is_protected_admin(target) and action in {
            "deactivate",
            "suspend",
            "remove",
            "role",
        }:
            self._require_other_role_manager(actor, target)
        return True

    # ── Branch access ──────────────────────────────────────────
    def branch_ids_for(self, user):
        """Return None for 'all branches', else a list of allowed branch ids."""
        if user is None:
            return []
        scope = (getattr(user, "branch_scope", "all") or "all").strip().lower()
        if scope == "all":
            if self.is_protected_admin(user) or not self.is_rbac_managed(user):
                return None
            return None
        ids = [row.branch_id for row in user.employee_branches.all()]
        if not ids and getattr(user, "branch_id", None):
            ids = [user.branch_id]
        return ids

    def can_access_branch(self, user, branch_id, *, include_unassigned=False):
        if branch_id is None:
            return include_unassigned
        allowed = self.branch_ids_for(user)
        if allowed is None:
            return True
        return int(branch_id) in allowed

    def assign_branches(self, user, branch_ids, *, scope, actor, reason=""):
        self._require_employees_permission(actor, "employees.edit")
        before = {
            "branches": [row.branch_id for row in user.employee_branches.all()],
            "scope": user.branch_scope,
        }
        if scope in {"all", "assigned", "department", "assigned_records", "own"}:
            user.branch_scope = scope
        for row in list(user.employee_branches.all()):
            db.session.delete(row)
        db.session.flush()
        for branch_id in set(int(b) for b in branch_ids or []):
            db.session.add(EmployeeBranch(user_id=user.id, branch_id=branch_id))
        db.session.flush()
        self._audit(
            actor,
            "employee_branches_changed",
            user,
            before=before,
            after={
                "branches": sorted({int(b) for b in branch_ids or []}),
                "scope": user.branch_scope,
            },
            change_summary=f"Branch access updated for {user.name}.",
            metadata={"reason": reason},
        )

    # ── Temporary access ───────────────────────────────────────
    def add_temporary_permission(
        self, user, permission, *, starts_at, ends_at, actor, reason=""
    ):
        if not valid_permission(permission):
            raise ValueError(f"Unknown permission: {permission}")
        if ends_at <= starts_at:
            raise ValueError("End time must be after the start time.")
        self._authorize_grant(actor, permission)
        self._clear_cache(user)
        db.session.add(
            TemporaryPermission(
                user_id=user.id,
                permission=permission,
                starts_at=starts_at,
                ends_at=ends_at,
                granted_by=getattr(actor, "id", None),
                reason=reason,
            )
        )
        db.session.flush()
        self._audit(
            actor,
            "employee_temporary_permission",
            user,
            before={"permission": permission, "active": False},
            after={
                "permission": permission,
                "starts_at": starts_at.isoformat(),
                "ends_at": ends_at.isoformat(),
                "active": True,
            },
            change_summary=f"Temporary {permission} granted to {user.name}.",
            metadata={"reason": reason},
        )

    def active_temporary_permissions(self, user, now=None):
        now = now or utcnow()
        return [
            row
            for row in TemporaryPermission.query.filter_by(user_id=user.id)
            .order_by(TemporaryPermission.ends_at.asc())
            .all()
            if row.starts_at <= now <= row.ends_at
        ]

    def list_temporary_permissions(self, user):
        return (
            TemporaryPermission.query.filter_by(user_id=user.id)
            .order_by(TemporaryPermission.created_at.desc())
            .all()
        )

    def purge_expired_temporary(self, now=None):
        now = now or utcnow()
        result = TemporaryPermission.query.filter(TemporaryPermission.ends_at < now).delete()
        if result:
            self._clear_cache()
        return result

    # ── Sessions ───────────────────────────────────────────────
    def create_session(self, user, *, ip=None, user_agent=None) -> tuple:
        token = secrets.token_urlsafe(32)
        session = UserSession(
            user_id=user.id,
            token_hash=_token_hash(token),
            ip_address=ip if ip is not None else _client_ip(),
            user_agent=(user_agent or _user_agent())[:255],
        )
        db.session.add(session)
        db.session.flush()
        return session, token

    def active_sessions(self, user, *, now=None):
        now = now or utcnow()
        return [
            s
            for s in UserSession.query.filter_by(user_id=user.id)
            .order_by(UserSession.created_at.desc())
            .all()
            if s.revoked_at is None
            and not (
                user.force_logout_before is not None
                and s.created_at < user.force_logout_before
            )
        ]

    def is_session_valid(self, session_id, token, user, *, now=None) -> bool:
        if not session_id or not token or user is None:
            return False
        session = db.session.get(UserSession, int(session_id))
        if session is None or session.user_id != user.id:
            return False
        if session.revoked_at is not None:
            return False
        if session.token_hash != _token_hash(token):
            return False
        if user.force_logout_before is not None and session.created_at < user.force_logout_before:
            return False
        session.last_seen_at = now or utcnow()
        return True

    def revoke_session(self, session_id, *, actor=None, user=None):
        session = db.session.get(UserSession, int(session_id))
        if session is None:
            return False
        if user is not None and session.user_id != user.id:
            return False
        if session.revoked_at is None:
            session.revoked_at = utcnow()
            self._audit(
                actor,
                "employee_session_revoked",
                session.user,
                before={"session_id": session.id, "revoked": False},
                after={"session_id": session.id, "revoked": True},
                change_summary=f"Session {session.id} revoked.",
            )
        return True

    def revoke_all_sessions(self, user, *, actor=None):
        now = utcnow()
        count = 0
        for session in UserSession.query.filter_by(user_id=user.id).all():
            if session.revoked_at is None:
                session.revoked_at = now
                count += 1
        if count:
            user.force_logout_before = now
            self._audit(
                actor,
                "employee_all_sessions_revoked",
                user,
                before={"active_sessions": count},
                after={"active_sessions": 0},
                change_summary=f"All {count} session(s) revoked for {user.name}.",
            )
        return count

    # ── Field-level masking ────────────────────────────────────
    def has_field_access(self, user, field_key):
        permission = FIELD_ACCESS_KEYS.get(field_key)
        if permission is None:
            return True
        return self.can(user, permission)

    def sensitive_field_access(self, user):
        return {
            field: self.has_field_access(user, field) for field in FIELD_ACCESS_KEYS
        }

    @staticmethod
    def mask_mobile(value):
        value = (value or "").strip()
        if not value:
            return value
        digits = "".join(ch for ch in value if ch.isdigit())
        if len(digits) >= 6:
            return f"+91 XXXXX {digits[-5:]}"
        return "XXXXXXXXXX"

    @staticmethod
    def mask_email(value):
        value = (value or "").strip()
        if not value or "@" not in value:
            return value
        local, _, domain = value.partition("@")
        if not local:
            return value
        return f"{local[0]}***@{domain}"

    @staticmethod
    def mask_gift_card_code(value):
        value = (value or "").strip()
        digits = "".join(ch for ch in value if ch.isdigit())
        if len(digits) >= 4:
            return f"XXXX-XXXX-{digits[-4:]}"
        return "XXXX-XXXX-XXXX"

    @staticmethod
    def mask_payment_reference(value):
        value = (value or "").strip()
        digits = "".join(ch for ch in value if ch.isdigit())
        if len(digits) >= 4:
            return f"•••• {digits[-4:]}"
        return "••••"

    def mask_value(self, value, field_key):
        return self.mask_for_user(None, value, field_key)

    def mask_for_user(self, user, value, field_key):
        if value in (None, ""):
            return value
        if self.has_field_access(user, field_key):
            return value
        if field_key == "customer_mobile":
            return self.mask_mobile(value)
        if field_key == "customer_email":
            return self.mask_email(value)
        if field_key == "gift_card_code":
            return self.mask_gift_card_code(value)
        if field_key == "payment_references":
            return self.mask_payment_reference(value)
        return self.mask_email(str(value))

    # ── Approval workflows ─────────────────────────────────────
    def ensure_default_approval_workflows(self, commit=True):
        for permission, (threshold, role, approvers, expiry) in APPROVAL_GATED_PERMISSIONS.items():
            module = MODULE_BY_PERMISSION.get(permission, "settings")
            workflow = ApprovalWorkflow.query.filter_by(
                module=module, action=permission
            ).first()
            if workflow is None:
                workflow = ApprovalWorkflow(
                    name=f"{MODULE_LABELS.get(module, module)} — {PERMISSION_LABELS.get(permission, permission)}",
                    module=module,
                    action=permission,
                    permission=permission,
                    threshold=threshold,
                    required_role=role,
                    num_approvers=approvers,
                    expiry_minutes=expiry,
                    is_active=True,
                )
                db.session.add(workflow)
        if commit:
            db.session.commit()

    def workflow_for(self, permission, amount=0):
        amount = Decimal(str(amount or 0))
        return (
            ApprovalWorkflow.query.filter_by(
                permission=permission, is_active=True
            )
            .order_by(ApprovalWorkflow.threshold.desc())
            .first()
        )

    def requires_approval(self, user, permission, amount=0):
        """Return (workflow|None, existing_pending|None)."""
        if not self.is_rbac_managed(user) or self.is_super_admin(user):
            return None, None
        workflow = self.workflow_for(permission, amount)
        if workflow is None or Decimal(str(amount or 0)) < Decimal(str(workflow.threshold or 0)):
            return None, None
        pending = (
            ApprovalRequest.query.filter_by(
                requester_id=user.id,
                permission=permission,
                status="pending",
            )
            .first()
        )
        return workflow, pending

    def create_approval_request(
        self,
        requester,
        permission,
        *,
        amount=0,
        target_type=None,
        target_id=None,
        payload=None,
    ):
        workflow, existing = self.requires_approval(requester, permission, amount)
        if workflow is None:
            return None
        if existing is not None:
            raise ValueError("You already have a pending approval for this action.")
        from datetime import timedelta

        request = ApprovalRequest(
            workflow_id=workflow.id,
            requester_id=requester.id,
            module=workflow.module,
            action=workflow.action,
            permission=permission,
            target_type=target_type,
            target_id=str(target_id) if target_id is not None else None,
            amount=amount,
            payload_json=json.dumps(payload, default=str) if payload else None,
            status="pending",
            branch_id=getattr(requester, "branch_id", None),
            expires_at=utcnow()
            + timedelta(minutes=int(workflow.expiry_minutes or 1440)),
        )
        db.session.add(request)
        db.session.flush()
        self._audit(
            requester,
            "approval_request_created",
            request,
            after={
                "permission": permission,
                "amount": str(amount or 0),
                "status": request.status,
            },
            change_summary=f"Approval requested for {permission}.",
        )
        return request

    def _is_self_approval(self, approval_request, approver) -> bool:
        return approval_request.requester_id == approver.id

    def pending_requests(self, approver=None, *, user_id=None):
        query = ApprovalRequest.query
        if user_id is not None:
            query = query.filter(ApprovalRequest.requester_id == user_id)
        if approver is not None and not self.is_super_admin(approver):
            from utils.permissions import has_role, ADMIN_PORTAL_ROLES

            if not has_role(approver, *ADMIN_PORTAL_ROLES):
                query = query.filter(ApprovalRequest.requester_id == -1)
        return (
            query.order_by(ApprovalRequest.created_at.desc())
            .limit(200)
            .all()
        )

    def vote(self, approval_request, approver, decision, *, reason=""):
        """Returns (status, message)."""
        if approval_request.status != "pending":
            return approval_request.status, "This approval request is no longer pending."
        if self._is_self_approval(approval_request, approver):
            raise PermissionError(
                "You cannot approve your own request (separation of duties)."
            )
        if decision not in {"approved", "rejected"}:
            raise ValueError("Invalid decision.")
        existing = (
            ApprovalVote.query.filter_by(
                approval_request_id=approval_request.id, approver_id=approver.id
            ).first()
        )
        if existing:
            return approval_request.status, "You already voted on this request."
        db.session.add(
            ApprovalVote(
                approval_request_id=approval_request.id,
                approver_id=approver.id,
                decision=decision,
                reason=reason,
            )
        )
        workflow = approval_request.workflow
        approvals = approval_request.votes.filter_by(decision="approved").count()
        rejects = approval_request.votes.filter_by(decision="rejected").count()
        required = int((workflow.num_approvers if workflow else 1) or 1)
        self._audit(
            approver,
            f"approval_{decision}",
            approval_request,
            before={"status": approval_request.status},
            after={"decision": decision, "reason": reason},
            change_summary=f"Approval {decision} for {approval_request.permission}.",
        )
        if decision == "rejected" and rejects > 0:
            approval_request.status = "rejected"
            approval_request.resolved_at = utcnow()
            db.session.flush()
            return "rejected", "Approval request rejected."
        if approvals >= required:
            approval_request.status = "approved"
            db.session.flush()
            return "approved", "Approval granted."
        return approval_request.status, "Approval recorded — awaiting more approvers."

    def expire_stale(self, now=None):
        now = now or utcnow()
        stale = ApprovalRequest.query.filter(
            ApprovalRequest.status == "pending",
            ApprovalRequest.expires_at.isnot(None),
            ApprovalRequest.expires_at < now,
        ).all()
        for req in stale:
            req.status = "expired"
            req.resolved_at = now
        return len(stale)

    # ── Audit helper ───────────────────────────────────────────
    def _audit(self, actor, action, target, *, before=None, after=None, change_summary="", metadata=None):
        from bootstrap import get_container

        try:
            get_container().audit_service.log(
                actor,
                action,
                target.__class__.__name__ if target is not None else "Rbac",
                getattr(target, "id", None),
                before=before,
                after=after,
                change_summary=change_summary,
                metadata=metadata,
            )
        except Exception:
            db.session.rollback()

    # ── Employee lifecycle helpers ─────────────────────────────
    def _require_employees_permission(self, actor, permission):
        if not self.can(actor, permission):
            raise PermissionError(f"Missing permission: {permission}")

    def set_employee_status(self, user, status, *, actor, reason=""):
        if status not in {
            "invited",
            "active",
            "inactive",
            "temporarily_suspended",
            "locked",
            "resigned",
            "terminated",
            "access_expired",
        }:
            raise ValueError("Unknown employee status.")
        self.can_manage(actor, user, action="status")
        before = {"employee_status": user.employee_status, "is_active": user.is_active}
        user.employee_status = status
        user.is_active = status == "active" or status == "invited"
        if status != "active":
            self.revoke_all_sessions(user, actor=actor)
        db.session.flush()
        self._audit(
            actor,
            "employee_status_changed",
            user,
            before=before,
            after={
                "employee_status": status,
                "is_active": user.is_active,
            },
            change_summary=f"Employee {user.name} set to {status}.",
            metadata={"reason": reason},
        )
        return status

    def remove_employee(self, user, *, actor, reason=""):
        self.can_manage(actor, user, action="remove")
        before = {"employee_status": user.employee_status}
        user.employee_status = "terminated"
        user.is_active = False
        user.rbac_enabled = False
        self.revoke_all_sessions(user, actor=actor)
        for row in list(user.employee_branches.all()):
            db.session.delete(row)
        db.session.flush()
        self._audit(
            actor,
            "employee_removed",
            user,
            before=before,
            after={"employee_status": "terminated"},
            change_summary=f"Employee {user.name} removed (soft delete).",
            metadata={"reason": reason},
        )
        return user

    def reset_access(self, user, *, actor, reason=""):
        before = {
            "must_change_password": user.must_change_password,
            "employee_status": user.employee_status,
        }
        user.must_change_password = True
        user.invite_token = None
        user.invite_token_expires_at = None
        self.revoke_all_sessions(user, actor=actor)
        db.session.flush()
        self._audit(
            actor,
            "employee_access_reset",
            user,
            before=before,
            after={"must_change_password": True},
            change_summary=f"Access reset for {user.name}.",
            metadata={"reason": reason},
        )

    def employee_status_allows_login(self, user) -> bool:
        return (
            user.is_active
            and (user.employee_status or "active").strip().lower() in {"active", "invited"}
            and user.is_employee_access_active
        )

    def enforce_session_and_status(self, user):
        """Used in admin-portal before_request. Returns a redirect/response or None."""
        from flask import session as flask_session

        if user is None or not getattr(user, "is_authenticated", False):
            return None
        if not self.employee_status_allows_login(user):
            from flask_login import logout_user

            logout_user()
            flask_session.clear()
            return ("Your employee account is no longer active.", 403)
        session_id = flask_session.get("user_session_id")
        session_token = flask_session.get("user_session_token")
        if session_id is not None:
            valid = self.is_session_valid(session_id, session_token, user)
            if not valid:
                from flask_login import logout_user

                logout_user()
                flask_session.clear()
                return ("Your session has been revoked. Please sign in again.", 403)
        return None
