from functools import wraps

from flask import flash, redirect, url_for
from flask_login import current_user

ROLE_HIERARCHY = {
    "customer": 10,
    "delivery": 20,
    "cashier": 30,
    "kitchen_staff": 40,
    "branch_manager": 50,
    "admin": 60,
    "super_admin": 70,
}

ADMIN_PORTAL_ROLES = {"super_admin", "admin", "branch_manager", "cashier", "kitchen_staff"}


def has_role(user, *roles):
    if user is None:
        return False
    normalized_roles = {(role or "").strip().lower() for role in roles}
    return (getattr(user, "role", "") or "").strip().lower() in normalized_roles


def role_meets_minimum(user, minimum_role):
    current_level = ROLE_HIERARCHY.get((getattr(user, "role", "") or "").strip().lower(), 0)
    minimum_level = ROLE_HIERARCHY.get((minimum_role or "").strip().lower(), 0)
    return current_level >= minimum_level


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
