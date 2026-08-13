from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user

from bootstrap import get_container
from clock import utcnow
from models import (
    AttendanceRecord,
    Branch,
    BranchInventory,
    BranchPurchaseRequest,
    Order,
    ProductVariant,
    RawMaterial,
    StockTransfer,
    User,
    db,
)
from utils.permissions import has_role


branch_bp = Blueprint("branch", __name__)

BRANCH_PLACEHOLDER_MODULES = {
    "pos": "Branch POS",
    "transfers": "Stock Transfers",
    "cash": "Cash Management",
    "purchase-requests": "Purchase Requests",
    "reports": "Reports",
}


def is_branch_user():
    return has_role(current_user, "branch_manager", "branch_staff")


def is_admin_preview():
    return current_user.is_authenticated and has_role(current_user, "admin", "super_admin")


def selected_branch():
    if is_branch_user():
        if not current_user.branch_id:
            abort(403)
        return db.get_or_404(Branch, current_user.branch_id)

    if is_admin_preview():
        branch_id = request.args.get("branch_id", type=int)
        branch = db.session.get(Branch, branch_id) if branch_id else None
        if branch is None:
            branch = Branch.query.filter_by(is_active=True).order_by(Branch.name.asc()).first()
        if branch is None:
            abort(404)
        return branch

    abort(403)


@branch_bp.before_request
def enforce_branch_access():
    if not current_user.is_authenticated:
        flash("Authentication required.", "danger")
        return redirect(url_for("auth.login", next=request.full_path.rstrip("?")))
    if is_branch_user() or is_admin_preview():
        return None
    abort(403)


def branch_url(endpoint, **values):
    branch = values.pop("branch", None)
    if is_admin_preview():
        branch_id = values.pop("branch_id", None) or request.args.get("branch_id")
        if branch is not None:
            branch_id = branch.id
        if branch_id:
            values["branch_id"] = branch_id
    return url_for(endpoint, **values)


def branch_shell_context(branch):
    return {
        "branch": branch,
        "admin_preview": is_admin_preview() and not is_branch_user(),
        "branch_url": branch_url,
        "sync_status": {
            "state": "Online",
            "pending": 0,
            "message": "TiDB is authoritative; offline writes stay queued until confirmed.",
        },
    }


def branch_order_query(branch):
    return Order.query.filter(Order.branch_id == branch.id)


def branch_order_or_404(order_id, branch):
    order = db.get_or_404(Order, order_id)
    if int(order.branch_id or 0) != int(branch.id):
        abort(404)
    return order


@branch_bp.route("/")
def dashboard():
    branch = selected_branch()
    today = utcnow().date()
    orders_today = branch_order_query(branch).filter(db.func.date(Order.placed_at) == today).count()
    pending_orders = branch_order_query(branch).filter(
        Order.status.in_(["PLACED", "CONFIRMED", "PREPARING", "PACKED", "READY_FOR_PICKUP"])
    ).count()
    low_stock = BranchInventory.query.filter(
        BranchInventory.branch_id == branch.id,
        BranchInventory.min_stock > 0,
        BranchInventory.quantity <= BranchInventory.min_stock,
    ).count()
    incoming_transfers = StockTransfer.query.filter(
        StockTransfer.destination_branch_id == branch.id,
        StockTransfer.status.in_(["PREPARED", "DISPATCHED", "IN_TRANSIT"]),
    ).count()
    staff_count = User.query.filter(
        User.branch_id == branch.id,
        User.is_active.is_(True),
        User.role.in_(["branch_manager", "branch_staff", "cashier", "kitchen_staff"]),
    ).count()
    purchase_requests = BranchPurchaseRequest.query.filter(
        BranchPurchaseRequest.branch_id == branch.id,
        BranchPurchaseRequest.status.in_(["SUBMITTED", "UNDER_REVIEW", "APPROVED"]),
    ).count()
    return render_template(
        "branch/dashboard.html",
        orders_today=orders_today,
        pending_orders=pending_orders,
        low_stock=low_stock,
        incoming_transfers=incoming_transfers,
        staff_count=staff_count,
        purchase_requests=purchase_requests,
        **branch_shell_context(branch),
    )


@branch_bp.route("/orders")
def orders():
    branch = selected_branch()
    rows = branch_order_query(branch).order_by(Order.placed_at.desc()).limit(100).all()
    return render_template("branch/orders.html", orders=rows, **branch_shell_context(branch))


@branch_bp.route("/orders/<int:order_id>")
def order_detail(order_id):
    branch = selected_branch()
    order = branch_order_or_404(order_id, branch)
    return render_template("branch/order_detail.html", order=order, **branch_shell_context(branch))


@branch_bp.route("/stock")
def stock():
    branch = selected_branch()
    variants = (
        ProductVariant.query.filter_by(branch_id=branch.id)
        .order_by(ProductVariant.name.asc())
        .all()
    )
    materials = (
        RawMaterial.query.filter_by(branch_id=branch.id, is_active=True)
        .order_by(RawMaterial.name.asc())
        .all()
    )
    inventory = (
        BranchInventory.query.filter_by(branch_id=branch.id)
        .order_by(BranchInventory.updated_at.desc())
        .all()
    )
    return render_template(
        "branch/stock.html",
        variants=variants,
        materials=materials,
        inventory=inventory,
        **branch_shell_context(branch),
    )


@branch_bp.route("/workforce")
def workforce():
    branch = selected_branch()
    staff = User.query.filter(User.branch_id == branch.id).order_by(User.name.asc()).all()
    attendance = (
        AttendanceRecord.query.filter_by(branch_id=branch.id)
        .order_by(AttendanceRecord.created_at.desc())
        .limit(25)
        .all()
    )
    return render_template(
        "branch/workforce.html",
        staff=staff,
        attendance=attendance,
        **branch_shell_context(branch),
    )


@branch_bp.route("/<module_name>")
def placeholder(module_name):
    if module_name not in BRANCH_PLACEHOLDER_MODULES:
        abort(404)
    branch = selected_branch()
    return render_template(
        "branch/placeholder.html",
        module_title=BRANCH_PLACEHOLDER_MODULES[module_name],
        **branch_shell_context(branch),
    )
