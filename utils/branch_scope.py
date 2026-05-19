"""Branch-level query scoping for multi-branch operators."""

from flask_login import current_user


def branch_filter(query, model):
    if not getattr(current_user, "is_authenticated", False):
        return query
    if current_user.role not in {"branch_manager"}:
        return query
    if current_user.branch_id is None:
        return query
    if hasattr(model, "branch_id"):
        return query.filter(model.branch_id == current_user.branch_id)
    return query


def default_branch_id(app):
    return app.config.get("DEFAULT_BRANCH_ID")
