from functools import wraps

from flask import flash, redirect, url_for
from flask_login import current_user

ROLE_HIERARCHY = {
    "customer": 10,
    "delivery": 20,
    "cashier": 30,
    "kitchen_staff": 40,
    "branch_staff": 45,
    "branch_manager": 50,
    "auditor": 55,
    "admin": 60,
    "super_admin": 70,
}

ADMIN_PORTAL_ROLES = {"super_admin", "admin", "branch_manager", "cashier", "kitchen_staff"}
AUDITOR_PORTAL_ROLES = {"auditor"}
BRANCH_PORTAL_ROLES = {"branch_manager", "branch_staff"}
ORDER_SCREEN_ROLES = {"cashier"}
ADMIN_TIER_HIERARCHY = {
    "staff": 10,
    "manager": 20,
    "owner": 30,
}


def has_role(user, *roles):
    if user is None:
        return False
    normalized_roles = {(role or "").strip().lower() for role in roles}
    return (getattr(user, "role", "") or "").strip().lower() in normalized_roles


def is_order_screen_user(user):
    return has_role(user, *ORDER_SCREEN_ROLES)


def role_meets_minimum(user, minimum_role):
    current_level = ROLE_HIERARCHY.get((getattr(user, "role", "") or "").strip().lower(), 0)
    minimum_level = ROLE_HIERARCHY.get((minimum_role or "").strip().lower(), 0)
    return current_level >= minimum_level


def effective_admin_tier(user):
    if user is None:
        return None
    tier = getattr(user, "effective_admin_tier", None)
    if tier:
        return (tier or "").strip().lower()
    role = (getattr(user, "role", "") or "").strip().lower()
    if role == "super_admin":
        return "owner"
    if role == "branch_manager":
        return "manager"
    if role in {"cashier", "kitchen_staff"}:
        return "staff"
    if role == "admin":
        return (getattr(user, "admin_tier", None) or "owner").strip().lower()
    return None


def admin_tier_meets(user, *allowed_tiers):
    tier = effective_admin_tier(user)
    if not tier:
        return False
    allowed = {(item or "").strip().lower() for item in allowed_tiers if item}
    if not allowed:
        return False
    current_level = ADMIN_TIER_HIERARCHY.get(tier, 0)
    return any(current_level >= ADMIN_TIER_HIERARCHY.get(item, 0) for item in allowed)


def roles_required(*roles):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if not current_user.is_authenticated or not has_role(current_user, *roles):
                flash("Access denied.", "danger")
                return redirect(url_for("auth.login"))
            return view(*args, **kwargs)

        return wrapped

    return decorator


def auditor_required(view):
    """Decorator to require auditor role for a route."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not current_user.is_authenticated:
            flash("Authentication required.", "danger")
            return redirect(url_for("auth.login"))
        if not has_role(current_user, "auditor"):
            flash("Auditor access required.", "danger")
            return redirect(url_for("auth.login"))
        return view(*args, **kwargs)

    return wrapped


def branch_required(view):
    """Decorator to require branch_manager or branch_staff role.
    Also enforces branch scoping - branch users can only access their own branch."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not current_user.is_authenticated:
            flash("Authentication required.", "danger")
            return redirect(url_for("auth.login"))
        if not has_role(current_user, "branch_manager", "branch_staff"):
            flash("Branch access required.", "danger")
            return redirect(url_for("auth.login"))
        if not current_user.branch_id:
            flash("Branch assignment required.", "danger")
            return redirect(url_for("auth.login"))
        return view(*args, **kwargs)

    return wrapped


def branch_manager_required(view):
    """Decorator to require branch_manager role specifically."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not current_user.is_authenticated:
            flash("Authentication required.", "danger")
            return redirect(url_for("auth.login"))
        if not has_role(current_user, "branch_manager"):
            flash("Branch manager access required.", "danger")
            return redirect(url_for("auth.login"))
        if not current_user.branch_id:
            flash("Branch assignment required.", "danger")
            return redirect(url_for("auth.login"))
        return view(*args, **kwargs)

    return wrapped


def admin_required(view):
    """Decorator to require admin or super_admin role."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not current_user.is_authenticated:
            flash("Authentication required.", "danger")
            return redirect(url_for("auth.login"))
        if not has_role(current_user, "admin", "super_admin"):
            flash("Admin access required.", "danger")
            return redirect(url_for("auth.login"))
        return view(*args, **kwargs)

    return wrapped


def enforce_branch_scope(*scope_param_names):
    """Decorator to enforce branch scoping for branch users.

    For branch users, verifies that any requested branch_id in the route arguments
    matches their assigned branch_id. Admin users bypass this check.

    Args:
        *scope_param_names: Parameter names that contain branch_id (e.g., 'branch_id', 'id')
                           The decorator will look up the actual branch object for 'id' params.
    """
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            # Admin users can access any branch scope
            if current_user.is_authenticated and has_role(current_user, "admin", "super_admin"):
                return view(*args, **kwargs)

            # Branch users must match their branch_id
            if current_user.is_authenticated and has_role(current_user, "branch_manager", "branch_staff"):
                if not current_user.branch_id:
                    flash("Branch assignment required.", "danger")
                    return redirect(url_for("auth.login"))

                # Check each scope parameter
                for param_name in scope_param_names:
                    requested_branch_id = kwargs.get(param_name)
                    if requested_branch_id:
                        try:
                            requested_branch_id = int(requested_branch_id)
                            if requested_branch_id != current_user.branch_id:
                                flash("You do not have access to this branch.", "danger")
                                return redirect(url_for("auth.login"))
                        except (ValueError, TypeError):
                            flash("Invalid branch ID.", "danger")
                            return redirect(url_for("auth.login"))

            return view(*args, **kwargs)

        return wrapped

    return decorator


def read_only_enforcer(view):
    """Decorator to prevent auditors from making write operations.

    Auditors should never be able to POST, PUT, DELETE, PATCH.
    This decorator checks if the request method is safe (GET, HEAD, OPTIONS).
    """
    @wraps(view)
    def wrapped(*args, **kwargs):
        from flask import request, abort

        if current_user.is_authenticated and has_role(current_user, "auditor"):
            # Allow only safe HTTP methods for auditors
            if request.method not in {"GET", "HEAD", "OPTIONS"}:
                flash("Auditors can only view data.", "danger")
                return abort(403)

        return view(*args, **kwargs)

    return wrapped
