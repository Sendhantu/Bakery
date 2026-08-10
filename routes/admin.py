from flask import (
    Blueprint,
    render_template,
    redirect,
    url_for,
    flash,
    request,
    jsonify,
    current_app,
    abort,
    send_file,
)
from flask_login import login_required, current_user
from bootstrap import get_container
from clock import utcnow
from exceptions import ConflictError, ValidationError
from functools import wraps
import json
import os
import re
import secrets
from decimal import Decimal
from datetime import date, timedelta
from sqlalchemy.orm import selectinload
from realtime.events import (
    customer_room,
    emit_new_order,
    emit_order_cancelled,
    emit_order_refunded,
    emit_order_status_updated,
    emit_stock_updated,
    emit_support_message,
)
from utils.permissions import admin_tier_meets, effective_admin_tier, has_role
from models import (
    db,
    User,
    Product,
    PRODUCT_IMAGE_FIT_CHOICES,
    PRODUCT_IMAGE_FIT_VALUES,
    PRODUCT_IMAGE_POSITION_CHOICES,
    PRODUCT_IMAGE_POSITION_VALUES,
    ProductVariant,
    Category,
    Order,
    OrderItem,
    OrderStatusHistory,
    Payment,
    PosPaymentTransaction,
    Refund,
    Coupon,
    COUPON_AUDIENCE_CHOICES,
    COUPON_AUDIENCE_VALUES,
    COUPON_AUDIENCE_NEW_CUSTOMERS,
    Subscription,
    Message,
    Notification,
    DeliveryAgent,
    Delivery,
    DeliveryCashLedger,
    DeliveryZoneSetting,
    DeliveryDistanceBand,
    DeliveryPincodeRule,
    GST_ORDER_SOURCE_CHOICES,
    GST_ORDER_SOURCE_COUNTER_TAKEAWAY,
    GST_ORDER_SOURCE_ECOMMERCE_SWIGGY,
    GST_ORDER_SOURCE_ECOMMERCE_ZOMATO,
    GST_ORDER_SOURCE_VALUES,
    LoginHistory,
    Review,
    ModificationRequest,
    FinancialCategory,
    FinancialTransaction,
    StockMovement,
    TaxRate,
    TaxRecord,
    TDS_PAYMENT_TYPE_CHOICES,
    TDS_PAYMENT_TYPE_NONE,
    TDS_PAYMENT_TYPE_VALUES,
    Vendor,
    VendorProduct,
    PurchaseOrder,
    PurchaseOrderItem,
    RawMaterial,
    ProductMaterial,
    Supplier,
    Branch,
    ProductionPlan,
    ProductionBatch,
    MaterialBatch,
    MaterialDocument,
    BATCH_STATUS_LABELS,
    MATERIAL_DOCUMENT_TYPES,
    MATERIAL_DOCUMENT_TYPE_LABELS,
    MATERIAL_DOCUMENT_TYPE_VALUES,
    STOCK_MOVEMENT_REASON_LABELS,
    PaymentLink,
    GiftCard,
    GiftCardTransaction,
    RecurringSubscription,
    SubscriptionOrderLog,
    OccasionReminder,
    CorporateInquiry,
    CorporateInquiryStatusHistory,
    CorporateQuote,
    CustomerConsent,
    ConversionEvent,
    WebhookEventLog,
    SecurityEvent,
    NotificationTemplate,
    NotificationDeliveryLog,
    KitchenAlert,
    DiningArea,
    DiningTable,
    TableMenuScan,
    TableMenuSession,
    LoyaltyLedger,
    AuditLog,
    ApiUsageLog,
    AttendanceRecord,
    FraudAlert,
    FraudBlocklistEntry,
    CustomerRiskProfile,
    LocalEvent,
    OperationalAlert,
    PricingRule,
    QueueMetric,
    SalaryRecord,
    SearchAnalytics,
    StaffShift,
    SubscriptionSchedule,
    SyncConflict,
    get_loyalty_config,
    can_transition_order_status,
    get_allowed_order_statuses,
)
from services import (
    enrich_orders,
    generate_smart_triage_report,
    summarize_triage_report,
)
from services.review_reply_service import (
    generate_review_reply_draft,
    review_needs_attention,
)
from services.analytics_service import (
    PERIOD_LABELS,
    analytics_payload,
    default_granularity,
    period_bounds,
    top_selling_product,
    total_revenue,
)
from utils import (
    ADMIN_PORTAL_ROLES,
    parse_decimal,
    notify,
    check_and_send_inventory_alerts,
    has_role,
    is_order_screen_user,
    validate_password,
)
from datetime import datetime, timedelta, date, time
from sqlalchemy import false, func, or_
from sqlalchemy.exc import SQLAlchemyError
from decimal import Decimal

admin_bp = Blueprint("admin", __name__)

VENDOR_PAYMENT_METHOD_CHOICES = [
    ("BANK_TRANSFER", "Bank Transfer"),
    ("UPI", "UPI"),
    ("CASH", "Cash"),
    ("CARD", "Card"),
    ("CHEQUE", "Cheque"),
    ("CREDIT_TERMS", "Credit / Terms"),
]
VENDOR_PAYMENT_METHOD_LABELS = dict(VENDOR_PAYMENT_METHOD_CHOICES)
LIVE_ORDER_STATUSES = (
    "PLACED",
    "PREPARING",
    "PACKED",
    "OUT_FOR_DELIVERY",
    "READY_FOR_PICKUP",
    "ON_HOLD",
)
PAST_ORDER_STATUSES = ("DELIVERED", "CANCELLED", "REFUNDED")
ORDER_SCREEN_ALLOWED_ENDPOINTS = {
    "admin.pos_terminal",
    "admin.pos_terminal_success",
    "admin.pos_terminal_receipt",
    "admin.pos",
    "admin.pos_payment",
    "admin.pos_receipt",
}


@admin_bp.before_request
def ensure_admin_portal():
    if current_app.config.get("PORTAL_ROLE") != "admin":
        if current_user.is_authenticated and has_role(
            current_user, *ADMIN_PORTAL_ROLES
        ):
            from routes.auth import portal_url_for_role

            return redirect(portal_url_for_role("admin", url_for("admin.dashboard")))
        abort(404)

    if current_user.is_authenticated and is_order_screen_user(current_user):
        if request.endpoint == "admin.dashboard":
            return redirect(url_for("admin.pos"))
        if request.endpoint and request.endpoint not in ORDER_SCREEN_ALLOWED_ENDPOINTS:
            abort(403)

    if current_user.is_authenticated and has_role(current_user, *ADMIN_PORTAL_ROLES):
        section = admin_access_section_for_request()
        if not admin_user_has_section_access(current_user, section):
            try:
                get_container().audit_service.log(
                    current_user,
                    "admin_section_permission_denied",
                    "AdminRoute",
                    request.endpoint or request.path,
                    after={
                        "path": request.path,
                        "method": request.method,
                        "section": section,
                        "access": staff_portal_access_values(current_user),
                    },
                    change_summary="Portal section access check denied route access.",
                )
                db.session.commit()
            except Exception:
                db.session.rollback()
            return "You do not have access to this admin section.", 403


# ── Auth guard ───────────────────────────────────────────────
def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or not has_role(
            current_user, *ADMIN_PORTAL_ROLES
        ):
            flash("Admin access required.", "danger")
            return redirect(url_for("auth.login"))
        return f(*args, **kwargs)

    return decorated


def require_admin_tier(*allowed_tiers):
    """Restrict admin-portal routes by the user's effective admin tier."""
    normalized_tiers = tuple(
        (tier or "").strip().lower() for tier in allowed_tiers if tier
    )

    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if not current_user.is_authenticated or not admin_tier_meets(
                current_user,
                *normalized_tiers,
            ):
                try:
                    get_container().audit_service.log(
                        current_user if current_user.is_authenticated else None,
                        "admin_permission_denied",
                        "AdminRoute",
                        request.endpoint or request.path,
                        after={
                            "path": request.path,
                            "method": request.method,
                            "required_tiers": list(normalized_tiers),
                            "user_tier": (
                                effective_admin_tier(current_user)
                                if current_user.is_authenticated
                                else None
                            ),
                        },
                        change_summary="Admin tier check denied route access.",
                    )
                    db.session.commit()
                except Exception:
                    db.session.rollback()
                return (
                    "You do not have permission to access this admin section.",
                    403,
                )
            return f(*args, **kwargs)

        return decorated

    return decorator


def finance_required(f):
    """Finance module — restricted to owner-tier admins only."""
    return require_admin_tier("owner")(f)


def owner_required(f):
    return require_admin_tier("owner")(f)


def operations_required(f):
    return require_admin_tier("staff", "manager", "owner")(f)


def manager_required(f):
    return require_admin_tier("manager", "owner")(f)


def has_global_admin_data_access(user=None):
    """Owner admin roles can see every branch; operational roles are scoped."""
    user = user or current_user
    role = (getattr(user, "role", "") or "").strip().lower()
    return role == "super_admin" or (
        role == "admin" and admin_tier_meets(user, "owner")
    )


def current_admin_branch_id(user=None):
    user = user or current_user
    if has_global_admin_data_access(user):
        return None
    return getattr(user, "branch_id", None)


def admin_data_scope_label(user=None):
    user = user or current_user
    if has_global_admin_data_access(user):
        return "All branches"
    branch = getattr(user, "branch", None)
    if branch:
        return branch.name
    return "Unassigned branch data"


def _scoped_branch_criterion(branch_column, *, include_unassigned=False):
    if has_global_admin_data_access():
        return None
    branch_id = current_admin_branch_id()
    if branch_id is None:
        return branch_column.is_(None) if include_unassigned else false()
    if include_unassigned:
        return or_(branch_column == branch_id, branch_column.is_(None))
    return branch_column == branch_id


def scope_query_to_admin_branch(query, branch_column, *, include_unassigned=False):
    criterion = _scoped_branch_criterion(
        branch_column,
        include_unassigned=include_unassigned,
    )
    return query if criterion is None else query.filter(criterion)


def admin_can_access_branch(branch_id, *, include_unassigned=False):
    if has_global_admin_data_access():
        return True
    scoped_branch_id = current_admin_branch_id()
    if branch_id is None:
        return include_unassigned or scoped_branch_id is None
    return scoped_branch_id is not None and int(branch_id) == int(scoped_branch_id)


def abort_if_no_branch_access(branch_id, *, include_unassigned=False):
    if not admin_can_access_branch(branch_id, include_unassigned=include_unassigned):
        abort(403)


def scoped_order_query(query=None, *, include_unassigned=False):
    return scope_query_to_admin_branch(
        Order.query if query is None else query,
        Order.branch_id,
        include_unassigned=include_unassigned,
    )


def scoped_order_or_404(order_id, *, include_unassigned=False):
    order = db.get_or_404(Order, order_id)
    abort_if_no_branch_access(order.branch_id, include_unassigned=include_unassigned)
    return order


def scoped_variant_query(query=None):
    return scope_query_to_admin_branch(
        ProductVariant.query if query is None else query,
        ProductVariant.branch_id,
        include_unassigned=True,
    )


def scoped_variant_or_404(variant_id):
    variant = db.get_or_404(ProductVariant, variant_id)
    abort_if_no_branch_access(variant.branch_id, include_unassigned=True)
    return variant


def scoped_material_query(query=None):
    return scope_query_to_admin_branch(
        RawMaterial.query if query is None else query,
        RawMaterial.branch_id,
        include_unassigned=True,
    )


def scoped_material_or_404(material_id):
    material = db.get_or_404(RawMaterial, material_id)
    abort_if_no_branch_access(material.branch_id, include_unassigned=True)
    return material


def scoped_agent_query(query=None):
    return scope_query_to_admin_branch(
        DeliveryAgent.query if query is None else query,
        DeliveryAgent.branch_id,
        include_unassigned=False,
    )


def scoped_agent_or_404(agent_id):
    agent = db.get_or_404(DeliveryAgent, agent_id)
    abort_if_no_branch_access(agent.branch_id)
    return agent


def scoped_branch_query(query=None):
    if has_global_admin_data_access():
        return Branch.query if query is None else query
    branch_id = current_admin_branch_id()
    query = Branch.query if query is None else query
    return query.filter(Branch.id == branch_id) if branch_id else query.filter(false())


def scoped_branch_or_404(branch_id):
    branch = db.get_or_404(Branch, branch_id)
    if not has_global_admin_data_access() and int(branch.id) != int(current_admin_branch_id() or 0):
        abort(403)
    return branch


SUPPORT_STAFF_ROLE_PRIORITY = {
    "admin": 0,
    "super_admin": 0,
    "branch_manager": 1,
    "cashier": 2,
    "kitchen_staff": 3,
}

BRANCH_EMPLOYEE_ROLE_CHOICES = (
    ("branch_manager", "Branch Manager"),
    ("cashier", "Cashier / Order Taking"),
    ("kitchen_staff", "Kitchen Staff"),
)
BRANCH_EMPLOYEE_ROLE_LABELS = dict(BRANCH_EMPLOYEE_ROLE_CHOICES)
BRANCH_EMPLOYEE_ROLE_VALUES = set(BRANCH_EMPLOYEE_ROLE_LABELS)

STAFF_PORTAL_ROLE_CHOICES = (
    ("admin", "Admin Portal Staff"),
    *BRANCH_EMPLOYEE_ROLE_CHOICES,
)
STAFF_PORTAL_ROLE_LABELS = dict(STAFF_PORTAL_ROLE_CHOICES)
STAFF_PORTAL_ROLE_VALUES = set(STAFF_PORTAL_ROLE_LABELS)
STAFF_PORTAL_ACCESS_CHOICES = (
    ("dashboard", "Dashboard"),
    ("orders", "Live and Past Orders"),
    ("products", "Products"),
    ("categories", "Categories"),
    ("inventory", "Inventory"),
    ("raw_materials", "Raw Materials"),
    ("kds", "Kitchen Display"),
    ("pos", "Walk-in Orders / POS"),
    ("support", "Customer Support"),
    ("customers", "Customers"),
    ("branches", "Branches"),
    ("suppliers", "Suppliers"),
    ("vendors", "Vendors"),
    ("purchase_orders", "Purchase Orders"),
    ("production", "Production"),
    ("delivery_agents", "Delivery Agents"),
    ("delivery_cash", "Delivery Cash Ledger"),
    ("analytics", "Analytics and Demand Insights"),
    ("security", "Security"),
    ("notifications", "Notifications"),
    ("qr_menu", "Table QR Codes"),
    ("pricing", "Pricing and AI Offer Provision"),
    ("coupons", "Coupons"),
    ("gift_cards", "Gift Cards"),
    ("loyalty", "Loyalty"),
    ("staff", "Staff Management"),
    ("finance", "Finance"),
)
STAFF_PORTAL_ACCESS_LABELS = dict(STAFF_PORTAL_ACCESS_CHOICES)
STAFF_PORTAL_ACCESS_VALUES = set(STAFF_PORTAL_ACCESS_LABELS)
ALL_STAFF_ACCESS_KEYS = tuple(value for value, _label in STAFF_PORTAL_ACCESS_CHOICES)
STAFF_ROLE_DEFAULT_ACCESS = {
    "admin": ALL_STAFF_ACCESS_KEYS,
    "branch_manager": (
        "dashboard",
        "orders",
        "products",
        "categories",
        "inventory",
        "raw_materials",
        "kds",
        "pos",
        "support",
        "customers",
        "branches",
        "suppliers",
        "vendors",
        "purchase_orders",
        "production",
        "delivery_agents",
        "delivery_cash",
        "analytics",
        "security",
        "notifications",
        "qr_menu",
        "pricing",
        "coupons",
        "gift_cards",
        "loyalty",
    ),
    "cashier": ("pos",),
    "kitchen_staff": (
        "kds",
        "pos",
        "inventory",
        "raw_materials",
        "production",
        "support",
    ),
}
STAFF_ACCESS_PATH_SLUGS = {
    "": "dashboard",
    "products": "products",
    "categories": "categories",
    "orders": "orders",
    "modifications": "orders",
    "reviews": "customers",
    "customers": "customers",
    "corporate": "customers",
    "support": "support",
    "chat": "support",
    "inventory": "inventory",
    "raw-materials": "raw_materials",
    "suppliers": "suppliers",
    "vendors": "vendors",
    "purchase-orders": "purchase_orders",
    "branches": "branches",
    "delivery-settings": "branches",
    "production": "production",
    "batches": "production",
    "coupons": "coupons",
    "agents": "delivery_agents",
    "analytics": "analytics",
    "security": "security",
    "notifications": "notifications",
    "table-qr": "qr_menu",
    "qr-menu": "qr_menu",
    "demand-insights": "analytics",
    "loyalty": "loyalty",
    "gift-cards": "gift_cards",
    "forecasts": "pricing",
    "kds": "kds",
    "walk-in-orders": "pos",
    "pos": "pos",
    "pricing": "pricing",
    "subscriptions": "customers",
    "blocklist": "customers",
    "audit": "staff",
    "audit-log": "staff",
    "queue-monitor": "kds",
    "offline": "dashboard",
    "delivery": "delivery_agents",
    "delivery-cash": "delivery_cash",
    "qr-scanner": "pos",
    "finance": "finance",
    "sync_conflicts": "dashboard",
}


def _json_list(value):
    try:
        loaded = json.loads(value or "[]")
    except (TypeError, ValueError):
        return []
    if not isinstance(loaded, list):
        return []
    return [str(item).strip().lower() for item in loaded if str(item).strip()]


def staff_role_default_access(role):
    role = (role or "").strip().lower()
    return list(STAFF_ROLE_DEFAULT_ACCESS.get(role, STAFF_ROLE_DEFAULT_ACCESS["admin"]))


def staff_portal_access_values(user):
    if has_global_admin_data_access(user):
        return list(ALL_STAFF_ACCESS_KEYS)
    stored_values = [
        value
        for value in _json_list(getattr(user, "permissions", "[]"))
        if value in STAFF_PORTAL_ACCESS_VALUES
    ]
    if stored_values:
        return stored_values
    return staff_role_default_access(getattr(user, "role", "admin"))


def staff_portal_access_labels(user):
    if has_global_admin_data_access(user):
        return ["Full access"]
    return [
        STAFF_PORTAL_ACCESS_LABELS[value]
        for value in staff_portal_access_values(user)
        if value in STAFF_PORTAL_ACCESS_LABELS
    ]


def annotate_staff_access(users):
    for user in users:
        user.portal_access_values = staff_portal_access_values(user)
        user.portal_access_labels = staff_portal_access_labels(user)
        user.portal_role_label = STAFF_PORTAL_ROLE_LABELS.get(
            (user.role or "").strip().lower(),
            (user.role or "Staff").replace("_", " ").title(),
        )
    return users


def staff_access_from_form(role):
    selected = [
        value.strip().lower()
        for value in (
            request.form.getlist("portal_access")
            + request.form.getlist("portal_access[]")
        )
        if value and value.strip().lower() in STAFF_PORTAL_ACCESS_VALUES
    ]
    return selected or staff_role_default_access(role)


def parse_staff_joining_date():
    raw_value = (request.form.get("date_of_joining") or "").strip()
    if not raw_value:
        return None
    try:
        return date.fromisoformat(raw_value)
    except ValueError as exc:
        raise ValidationError("Date of joining must be a valid date.") from exc


def apply_staff_profile_from_form(user, role):
    user.staff_address = (request.form.get("staff_address") or "").strip()
    user.date_of_joining = parse_staff_joining_date()
    user.designation = (request.form.get("designation") or "").strip()
    user.emergency_contact = (request.form.get("emergency_contact") or "").strip()
    user.staff_notes = (request.form.get("staff_notes") or "").strip()
    user.permissions = json.dumps(staff_access_from_form(role))


def admin_access_section_for_request():
    endpoint = request.endpoint or ""
    if endpoint == "admin.dashboard":
        return "dashboard"
    path_parts = [part for part in (request.path or "").strip("/").split("/") if part]
    if not path_parts:
        return "dashboard"
    if path_parts[0] == "admin":
        slug = path_parts[1] if len(path_parts) > 1 else ""
    else:
        slug = path_parts[0]
    if slug == "api" and "analytics" in path_parts[1:3]:
        return "analytics"
    return STAFF_ACCESS_PATH_SLUGS.get(slug)


def admin_user_has_section_access(user, section):
    if not section or has_global_admin_data_access(user):
        return True
    return section in staff_portal_access_values(user)


def branch_employee_role_choices_for_current_user():
    if has_global_admin_data_access():
        return BRANCH_EMPLOYEE_ROLE_CHOICES
    return tuple(
        choice
        for choice in BRANCH_EMPLOYEE_ROLE_CHOICES
        if choice[0] in {"cashier", "kitchen_staff"}
    )


def branch_employee_admin_tier(role):
    return "manager" if role == "branch_manager" else "staff"


def validate_branch_employee_role(role):
    role = (role or "").strip().lower()
    if role not in BRANCH_EMPLOYEE_ROLE_VALUES:
        return None
    if role == "branch_manager" and not has_global_admin_data_access():
        return None
    return role


def branch_employee_redirect(branch_id):
    return redirect(url_for("admin.branches", _anchor=f"branch-{branch_id}"))


def branch_employee_or_404(branch_id, user_id):
    branch = scoped_branch_or_404(branch_id)
    employee = db.get_or_404(User, user_id)
    if int(employee.branch_id or 0) != int(branch.id):
        abort(404)
    if (employee.role or "").strip().lower() not in BRANCH_EMPLOYEE_ROLE_VALUES:
        abort(403)
    if employee.role == "branch_manager" and not has_global_admin_data_access():
        abort(403)
    return branch, employee


def support_staff_members():
    staff = (
        User.query.filter(
            User.role.in_(ADMIN_PORTAL_ROLES),
            User.is_active.is_(True),
        )
        .order_by(User.name.asc())
        .all()
    )
    return sorted(
        staff,
        key=lambda user: (
            SUPPORT_STAFF_ROLE_PRIORITY.get((user.role or "").lower(), 99),
            user.name or "",
        ),
    )


def support_staff_ids():
    return [staff.id for staff in support_staff_members()]


def support_recipient():
    staff = support_staff_members()
    return staff[0] if staff else None


def support_thread_filter(customer_id):
    staff_ids = support_staff_ids()
    if not staff_ids:
        return Message.id == -1
    return or_(
        (Message.sender_id == customer_id) & (Message.receiver_id.in_(staff_ids)),
        (Message.sender_id.in_(staff_ids)) & (Message.receiver_id == customer_id),
    )


def support_thread_messages(customer_id):
    return (
        Message.query.filter(support_thread_filter(customer_id))
        .order_by(Message.sent_at.asc(), Message.id.asc())
        .all()
    )


def support_thread_summaries(active_customer_id=None):
    staff_ids = support_staff_ids()
    if not staff_ids:
        return []

    customer_ids = {
        row[0]
        for row in db.session.query(Message.sender_id)
        .join(User, User.id == Message.sender_id)
        .filter(User.role == "customer", Message.receiver_id.in_(staff_ids))
        .distinct()
        .all()
    }
    customer_ids.update(
        row[0]
        for row in db.session.query(Message.receiver_id)
        .join(User, User.id == Message.receiver_id)
        .filter(User.role == "customer", Message.sender_id.in_(staff_ids))
        .distinct()
        .all()
    )
    if active_customer_id:
        customer_ids.add(active_customer_id)
    if not customer_ids:
        return []

    customers = {
        customer.id: customer
        for customer in User.query.filter(User.id.in_(customer_ids)).all()
    }
    summaries = []
    for customer_id in customer_ids:
        customer = customers.get(customer_id)
        if customer is None:
            continue
        last_message = (
            Message.query.filter(support_thread_filter(customer_id))
            .order_by(Message.sent_at.desc(), Message.id.desc())
            .first()
        )
        unread_count = Message.query.filter(
            Message.sender_id == customer_id,
            Message.receiver_id.in_(staff_ids),
            Message.is_read.is_(False),
        ).count()
        summaries.append(
            {
                "customer": customer,
                "last_message": last_message,
                "unread_count": unread_count,
            }
        )
    return sorted(
        summaries,
        key=lambda item: (
            item["last_message"].sent_at if item["last_message"] else item["customer"].created_at,
            item["last_message"].id if item["last_message"] else 0,
        ),
        reverse=True,
    )


def pending_support_message_count():
    staff_ids = support_staff_ids()
    if not staff_ids:
        return 0
    return (
        Message.query.join(User, User.id == Message.sender_id)
        .filter(
            User.role == "customer",
            Message.receiver_id.in_(staff_ids),
            Message.is_read.is_(False),
        )
        .count()
    )


def wants_live_fragment_response():
    if request.headers.get("X-Admin-Navigation") == "partial":
        return False
    return request.headers.get("X-Requested-With") == "XMLHttpRequest" or (
        request.accept_mimetypes.best == "application/json"
    )


def sync_delivery_status(order, new_status):
    delivery = order.delivery
    if delivery is None:
        return

    new_status = (new_status or "").strip().upper()
    agent = delivery.agent

    if new_status == "DELIVERED":
        delivery.status = "DELIVERED"
        delivery.delivered_time = utcnow()
        if agent:
            agent.availability = True
        return

    delivery.delivered_time = None
    if new_status == "OUT_FOR_DELIVERY":
        delivery.status = "OUT_FOR_DELIVERY"
        if agent:
            agent.availability = False
    elif new_status == "PACKED":
        delivery.status = "PACKED"
        if agent:
            agent.availability = False
    elif new_status == "CANCELLED":
        delivery.status = "CANCELLED"
        if agent:
            agent.availability = True
    else:
        delivery.status = "ASSIGNED"
        if agent:
            agent.availability = False


@admin_bp.context_processor
def inject_admin_nav():
    """Sidebar Chat badge — must be available on every admin page (base_admin.html)."""
    from flask_login import current_user as cu

    if not cu.is_authenticated or not has_role(cu, *ADMIN_PORTAL_ROLES):
        return {
            "pending_msgs": 0,
            "admin_tier": None,
            "can_admin_owner": False,
            "can_admin_manager": False,
            "can_admin_operations": False,
            "is_order_screen_user": False,
            "can_update_walkin_availability": False,
            "admin_start_endpoint": "admin.dashboard",
            "admin_data_scope": "No admin access",
            "admin_data_scope_global": False,
        }
    count = pending_support_message_count()
    order_screen_user = is_order_screen_user(cu)
    return {
        "pending_msgs": count,
        "admin_tier": effective_admin_tier(cu),
        "can_admin_owner": admin_tier_meets(cu, "owner"),
        "can_admin_manager": admin_tier_meets(cu, "manager", "owner"),
        "can_admin_operations": admin_tier_meets(cu, "staff", "manager", "owner"),
        "is_order_screen_user": order_screen_user,
        "can_update_walkin_availability": (
            not order_screen_user and admin_tier_meets(cu, "staff", "manager", "owner")
        ),
        "admin_start_endpoint": "admin.pos" if order_screen_user else "admin.dashboard",
        "admin_data_scope": admin_data_scope_label(cu),
        "admin_data_scope_global": has_global_admin_data_access(cu),
    }


@admin_bp.route("/sync_conflicts")
@admin_required
@manager_required
def list_sync_conflicts():
    page, per_page = 1, 100
    conflicts = (
        SyncConflict.query.order_by(SyncConflict.created_at.desc()).limit(500).all()
    )
    return render_template("admin/sync_conflicts.html", conflicts=conflicts)


# ── Image helper ─────────────────────────────────────────────
def apply_product_image(product):
    image_url = (request.form.get("image_url") or "").strip()
    if image_url:
        if not image_url.startswith(("http://", "https://")):
            raise ValidationError("Product image URL must start with http:// or https://.")
        product.image = image_url
        product.image_url = image_url

    if "image" in request.files and request.files["image"].filename:
        f = request.files["image"]
        uploaded_url = get_container().storage_service.upload_product_image(
            f,
            filename_prefix=(product.name or "product")
            .strip()
            .lower()
            .replace(" ", "-"),
        )
        product.image = uploaded_url
        product.image_url = uploaded_url


def apply_product_image_framing(product):
    image_fit = (request.form.get("image_fit") or "cover").strip()
    image_position = (request.form.get("image_position") or "center").strip()

    if image_fit not in PRODUCT_IMAGE_FIT_VALUES:
        raise ValidationError("Choose a valid product image frame fit.")
    if image_position not in PRODUCT_IMAGE_POSITION_VALUES:
        raise ValidationError("Choose a valid product image frame position.")

    product.image_fit = image_fit
    product.image_position = image_position


def product_is_eggless_from_form():
    egg_preference = (request.form.get("egg_preference") or "").strip()
    if egg_preference == "eggless":
        return True
    if egg_preference == "contains_egg":
        return False
    return bool(request.form.get("is_eggless"))


def apply_category_image(category):
    image_url = (request.form.get("image_url") or "").strip()
    if image_url:
        if not image_url.startswith(("http://", "https://")):
            raise ValidationError("Category image URL must start with http:// or https://.")
        category.image = image_url
        category.image_url = image_url

    if "image" in request.files and request.files["image"].filename:
        f = request.files["image"]
        uploaded_url = get_container().storage_service.upload_product_image(
            f,
            filename_prefix=(category.name or "category")
            .strip()
            .lower()
            .replace(" ", "-"),
        )
        category.image = uploaded_url
        category.image_url = uploaded_url


# ── Recipe sync ──────────────────────────────────────────────
def sync_product_materials(product):
    material_ids = request.form.getlist("recipe_material_id[]")
    quantities = request.form.getlist("recipe_quantity[]")
    submitted_ids = set()

    for mat_id, qty in zip(material_ids, quantities):
        if not mat_id:
            continue
        mat = db.session.get(RawMaterial, int(mat_id))
        if not mat:
            continue
        try:
            qty_dec = parse_decimal(qty, f"{mat.name} quantity")
        except ValueError:
            continue
        if qty_dec <= 0:
            continue
        submitted_ids.add(mat.id)
        existing = ProductMaterial.query.filter_by(
            product_id=product.id, raw_material_id=mat.id
        ).first()
        if existing:
            existing.quantity_required = qty_dec
        else:
            db.session.add(
                ProductMaterial(
                    product_id=product.id,
                    raw_material_id=mat.id,
                    quantity_required=qty_dec,
                )
            )

    for req in product.recipe_items.all():
        if req.raw_material_id not in submitted_ids:
            db.session.delete(req)


def build_order_payment_link(order):
    return PaymentLink.create_pending(
        user_id=order.user_id,
        order_id=order.id,
        purpose="ORDER",
        title=f"Payment for Order #{order.order_number}",
        amount=order.total,
        payment_method=order.payment_method,
        success_url=url_for("customer.order_detail", order_id=order.id),
        cancel_url=url_for("admin.order_detail", order_id=order.id),
        notes="Placeholder payment page for future gateway integration.",
    )


# ── DASHBOARD ────────────────────────────────────────────────
@admin_bp.route("/")
@admin_required
def dashboard():
    today = utcnow().date()
    realized_order_total = Order.total + func.coalesce(
        Order.gift_card_redemption_amount,
        0,
    )

    total_orders = scoped_order_query(Order.query, include_unassigned=True).count()
    today_orders = scoped_order_query(
        Order.query.filter(func.date(Order.placed_at) == today),
        include_unassigned=True,
    ).count()
    total_revenue = (
        scope_query_to_admin_branch(
            db.session.query(func.sum(realized_order_total)),
            Order.branch_id,
            include_unassigned=True,
        )
        .filter(Order.status != "CANCELLED")
        .scalar()
        or 0
    )
    today_revenue = (
        scope_query_to_admin_branch(
            db.session.query(func.sum(realized_order_total)),
            Order.branch_id,
            include_unassigned=True,
        )
        .filter(func.date(Order.placed_at) == today, Order.status != "CANCELLED")
        .scalar()
        or 0
    )
    if has_global_admin_data_access():
        total_customers = User.query.filter_by(role="customer").count()
    else:
        total_customers = (
            scoped_order_query(
                db.session.query(func.count(func.distinct(Order.user_id))),
                include_unassigned=True,
            ).scalar()
            or 0
        )
    pending_orders = scoped_order_query(
        Order.query.filter(Order.status.in_(["PLACED", "PREPARING"])),
        include_unassigned=True,
    ).count()
    low_stock_items = scoped_variant_query(
        ProductVariant.query.filter(ProductVariant.stock <= 5, ProductVariant.stock > 0)
    ).count()
    out_of_stock = scoped_variant_query(ProductVariant.query.filter_by(stock=0)).count()
    inactive_products = Product.query.filter_by(is_active=False).count()
    low_stock_materials = scoped_material_query(
        RawMaterial.query.filter(
            RawMaterial.is_active == True,
            RawMaterial.stock > 0,
            RawMaterial.stock <= RawMaterial.reorder_level,
        )
    ).count()
    out_of_stock_materials = scoped_material_query(
        RawMaterial.query.filter(RawMaterial.is_active == True, RawMaterial.stock <= 0)
    ).count()
    total_loyalty_points = (
        db.session.query(func.coalesce(func.sum(LoyaltyLedger.points), 0)).scalar() or 0
    )

    recent_orders = (
        scoped_order_query(Order.query, include_unassigned=True)
        .order_by(Order.placed_at.desc())
        .limit(8)
        .all()
    )
    enrich_orders(recent_orders)

    # Compare with previous 7-day window for quick trend badges
    window_start = today - timedelta(days=6)
    prev_window_start = today - timedelta(days=13)
    prev_window_end = today - timedelta(days=7)

    current_week_orders = scoped_order_query(
        Order.query.filter(
            func.date(Order.placed_at) >= window_start,
            func.date(Order.placed_at) <= today,
        ),
        include_unassigned=True,
    ).count()
    prev_week_orders = scoped_order_query(
        Order.query.filter(
            func.date(Order.placed_at) >= prev_window_start,
            func.date(Order.placed_at) <= prev_window_end,
        ),
        include_unassigned=True,
    ).count()

    current_week_revenue = (
        scope_query_to_admin_branch(
            db.session.query(func.sum(realized_order_total)),
            Order.branch_id,
            include_unassigned=True,
        )
        .filter(
            func.date(Order.placed_at) >= window_start,
            func.date(Order.placed_at) <= today,
            Order.status != "CANCELLED",
        )
        .scalar()
        or 0
    )
    prev_week_revenue = (
        scope_query_to_admin_branch(
            db.session.query(func.sum(realized_order_total)),
            Order.branch_id,
            include_unassigned=True,
        )
        .filter(
            func.date(Order.placed_at) >= prev_window_start,
            func.date(Order.placed_at) <= prev_window_end,
            Order.status != "CANCELLED",
        )
        .scalar()
        or 0
    )

    current_week_new_customers = User.query.filter(
        User.role == "customer",
        func.date(User.created_at) >= window_start,
        func.date(User.created_at) <= today,
    ).count()
    prev_week_new_customers = User.query.filter(
        User.role == "customer",
        func.date(User.created_at) >= prev_window_start,
        func.date(User.created_at) <= prev_window_end,
    ).count()

    def trend(current, previous):
        if previous == 0:
            if current == 0:
                return {"pct": 0, "dir": "flat"}
            return {"pct": 100, "dir": "up"}
        pct = round(((float(current) - float(previous)) / float(previous)) * 100, 1)
        if pct > 0:
            direction = "up"
        elif pct < 0:
            direction = "down"
        else:
            direction = "flat"
        return {"pct": abs(pct), "dir": direction}

    trend_revenue = trend(current_week_revenue, prev_week_revenue)
    trend_orders = trend(current_week_orders, prev_week_orders)
    trend_customers = trend(current_week_new_customers, prev_week_new_customers)

    labels, revenues, order_counts = [], [], []
    for i in range(6, -1, -1):
        d = today - timedelta(days=i)
        labels.append(d.strftime("%b %d"))
        rev = (
            scope_query_to_admin_branch(
                db.session.query(func.sum(realized_order_total)),
                Order.branch_id,
                include_unassigned=True,
            )
            .filter(func.date(Order.placed_at) == d, Order.status != "CANCELLED")
            .scalar()
            or 0
        )
        cnt = scoped_order_query(
            Order.query.filter(func.date(Order.placed_at) == d),
            include_unassigned=True,
        ).count()
        revenues.append(float(rev))
        order_counts.append(cnt)

    top_products_query = (
        db.session.query(Product.name, func.sum(OrderItem.quantity).label("sold"))
        .join(OrderItem, OrderItem.product_id == Product.id)
        .join(Order, Order.id == OrderItem.order_id)
    )
    top_products = (
        scope_query_to_admin_branch(
            top_products_query,
            Order.branch_id,
            include_unassigned=True,
        )
        .group_by(Product.id)
        .order_by(func.sum(OrderItem.quantity).desc())
        .limit(5)
        .all()
    )

    pending_msgs = Message.query.filter_by(
        receiver_id=current_user.id, is_read=False
    ).count()
    mod_requests = scope_query_to_admin_branch(
        ModificationRequest.query.join(Order),
        Order.branch_id,
        include_unassigned=True,
    ).filter(ModificationRequest.status == "PENDING").count()
    branch_count = (
        Branch.query.count()
        if has_global_admin_data_access()
        else (1 if current_admin_branch_id() else 0)
    )
    supplier_count = Supplier.query.count()
    supplier_alerts = Supplier.query.filter_by(is_active=False).count()

    context = dict(
        total_orders=total_orders,
        today_orders=today_orders,
        total_revenue=total_revenue,
        today_revenue=today_revenue,
        total_customers=total_customers,
        pending_orders=pending_orders,
        low_stock_items=low_stock_items,
        out_of_stock=out_of_stock,
        inactive_products=inactive_products,
        low_stock_materials=low_stock_materials,
        out_of_stock_materials=out_of_stock_materials,
        material_alerts=low_stock_materials + out_of_stock_materials,
        branch_count=branch_count,
        supplier_count=supplier_count,
        supplier_alerts=supplier_alerts,
        total_loyalty_points=int(total_loyalty_points),
        recent_orders=recent_orders,
        chart_labels=labels,
        chart_revenues=revenues,
        chart_order_counts=order_counts,
        top_products=top_products,
        pending_msgs=pending_msgs,
        mod_requests=mod_requests,
        trend_revenue=trend_revenue,
        trend_orders=trend_orders,
        trend_customers=trend_customers,
        current_date_label=today.strftime("%A, %d %B %Y"),
    )
    if wants_live_fragment_response():
        return jsonify(
            {
                "fragments": {
                    "#admin-dashboard-live": render_template(
                        "admin/_dashboard_live.html", **context
                    )
                }
            }
        )
    return render_template("admin/dashboard.html", **context)


@admin_bp.route("/triage")
@admin_required
@manager_required
def triage():
    pending_orders = (
        Order.query.filter(Order.status.in_(["PLACED", "PREPARING"]))
        .order_by(Order.placed_at.asc(), Order.id.asc())
        .all()
    )
    enrich_orders(pending_orders)

    report = generate_smart_triage_report(pending_orders)
    summary_payload = summarize_triage_report(report)
    notes = summary_payload.get("notes", {})
    order_map = {
        order_result["order"].id: order_result
        for grouped in report.get("grouped_results", {}).values()
        for order_result in grouped
    }

    context = {
        "report": report,
        "notes": notes,
        "order_map": order_map,
    }

    if wants_live_fragment_response():
        return jsonify(
            {
                "fragments": {
                    "#admin-triage-live": render_template(
                        "admin/_triage_live.html",
                        **context,
                    )
                }
            }
        )

    return render_template("admin/triage.html", **context)


@admin_bp.route("/demand-insights")
@admin_required
@manager_required
def demand_insights():
    payload = get_container().demand_service.dashboard_payload()
    return render_template("admin/demand_insights.html", **payload)


@admin_bp.route("/demand-insights/events", methods=["POST"])
@admin_required
@manager_required
def save_local_event():
    event_id = request.form.get("event_id", type=int)
    name = (request.form.get("name") or "").strip()
    event_date_raw = (request.form.get("event_date") or "").strip()
    expected_impact = (request.form.get("expected_impact") or "medium").strip().lower()
    notes = (request.form.get("notes") or "").strip() or None

    if expected_impact not in {"low", "medium", "high"}:
        expected_impact = "medium"
    if not name or not event_date_raw:
        flash("Event name and date are required.", "danger")
        return redirect(url_for("admin.demand_insights"))

    try:
        event_date = datetime.strptime(event_date_raw, "%Y-%m-%d").date()
    except ValueError:
        flash("Use a valid YYYY-MM-DD event date.", "danger")
        return redirect(url_for("admin.demand_insights"))

    event = db.session.get(LocalEvent, event_id) if event_id else None
    if event is None:
        event = LocalEvent(created_by=current_user.id)
        db.session.add(event)

    event.name = name
    event.event_date = event_date
    event.expected_impact = expected_impact
    event.notes = notes
    db.session.commit()
    flash("Local event saved for demand insights.", "success")
    return redirect(url_for("admin.demand_insights"))


@admin_bp.route("/demand-insights/events/<int:event_id>/delete", methods=["POST"])
@admin_required
@manager_required
def delete_local_event(event_id):
    event = db.session.get(LocalEvent, event_id)
    if event is None:
        flash("Local event was not found.", "warning")
        return redirect(url_for("admin.demand_insights"))
    db.session.delete(event)
    db.session.commit()
    flash("Local event removed.", "success")
    return redirect(url_for("admin.demand_insights"))


@admin_bp.route("/demand-insights/weather/refresh", methods=["POST"])
@admin_required
@manager_required
def refresh_demand_weather():
    forecast = get_container().weather_service.refresh_forecast()
    if forecast.get("status") == "ok":
        flash("Weather forecast refreshed.", "success")
    else:
        flash(
            forecast.get("message") or "Weather forecast could not be refreshed.",
            "warning",
        )
    return redirect(url_for("admin.demand_insights"))


# ── PRODUCT MANAGEMENT ───────────────────────────────────────
@admin_bp.route("/products")
@admin_required
@manager_required
def products():
    search = (request.args.get("q") or "").strip()
    get_container().inventory_service.backfill_missing_product_variants()
    query = Product.query
    if search:
        query = query.filter(Product.name.ilike(f"%{search}%"))
    products = query.order_by(Product.is_active.desc(), Product.created_at.desc()).all()
    return render_template("admin/products.html", products=products, search=search)


@admin_bp.route("/products/add", methods=["GET", "POST"])
@admin_required
@manager_required
def add_product():
    categories = Category.query.all()
    raw_materials = (
        RawMaterial.query.filter_by(is_active=True).order_by(RawMaterial.name).all()
    )
    if request.method == "POST":
        try:
            p = Product(
                name=request.form["name"],
                description=request.form.get("description"),
                ingredients=request.form.get("ingredients"),
                special_ingredient=(
                    request.form.get("special_ingredient") or ""
                ).strip(),
                preparation=request.form.get("preparation"),
                base_price=request.form["base_price"],
                category_id=request.form.get("category_id", type=int),
                is_eggless=product_is_eggless_from_form(),
                is_active=True,
                is_featured=bool(request.form.get("is_featured")),
                preorder_required=bool(request.form.get("preorder_required")),
                minimum_notice_hours=max(
                    1, request.form.get("minimum_notice_hours", type=int) or 24
                ),
                occasion_tags=request.form.get("occasion_tags", ""),
            )
            apply_product_image(p)
            apply_product_image_framing(p)
            db.session.add(p)
            db.session.flush()
            variant_rows = [
                {"id": None, "name": vn, "price": vp, "stock": vs}
                for vn, vp, vs in zip(
                    request.form.getlist("variant_name[]"),
                    request.form.getlist("variant_price[]"),
                    request.form.getlist("variant_stock[]"),
                )
            ]
            get_container().inventory_service.sync_product_variants(p, variant_rows)
            sync_product_materials(p)
        except ValidationError as exc:
            db.session.rollback()
            flash(str(exc), "danger")
            return render_template(
                "admin/product_form.html",
                product=None,
                categories=categories,
                raw_materials=raw_materials,
                image_fit_choices=PRODUCT_IMAGE_FIT_CHOICES,
                image_position_choices=PRODUCT_IMAGE_POSITION_CHOICES,
            )
        db.session.commit()
        get_container().audit_service.log(
            current_user,
            "product_created",
            "Product",
            p.id,
            after={"name": p.name, "base_price": str(p.base_price)},
            change_summary=f"Product created: {p.name}",
        )
        for variant in p.variants.all():
            emit_stock_updated(variant, include_customer=True)
        flash("Product added!", "success")
        return redirect(url_for("admin.products"))
    return render_template(
        "admin/product_form.html",
        product=None,
        categories=categories,
        raw_materials=raw_materials,
        image_fit_choices=PRODUCT_IMAGE_FIT_CHOICES,
        image_position_choices=PRODUCT_IMAGE_POSITION_CHOICES,
    )


@admin_bp.route("/products/<int:product_id>/edit", methods=["GET", "POST"])
@admin_required
@manager_required
def edit_product(product_id):
    p = db.get_or_404(Product, product_id)
    categories = Category.query.all()
    raw_materials = (
        RawMaterial.query.filter_by(is_active=True).order_by(RawMaterial.name).all()
    )
    if request.method == "POST":
        previous_variant_stock = {
            variant.id: variant.stock for variant in p.variants.all()
        }
        before_snapshot = {
            "base_price": str(p.base_price),
            "name": p.name,
            "is_active": p.is_active,
        }
        try:
            p.name = request.form["name"]
            p.description = request.form.get("description")
            p.ingredients = request.form.get("ingredients")
            p.special_ingredient = (
                request.form.get("special_ingredient") or ""
            ).strip()
            p.preparation = request.form.get("preparation")
            p.base_price = request.form["base_price"]
            p.category_id = request.form.get("category_id", type=int)
            p.is_eggless = product_is_eggless_from_form()
            p.is_featured = bool(request.form.get("is_featured"))
            p.is_active = bool(request.form.get("is_active"))
            p.preorder_required = bool(request.form.get("preorder_required"))
            p.minimum_notice_hours = max(
                1, request.form.get("minimum_notice_hours", type=int) or 24
            )
            p.occasion_tags = request.form.get("occasion_tags", "")
            apply_product_image(p)
            apply_product_image_framing(p)
            variant_rows = [
                {"id": vid, "name": vn, "price": vp, "stock": vs}
                for vid, vn, vp, vs in zip(
                    request.form.getlist("variant_id[]"),
                    request.form.getlist("variant_name[]"),
                    request.form.getlist("variant_price[]"),
                    request.form.getlist("variant_stock[]"),
                )
            ]
            get_container().inventory_service.sync_product_variants(p, variant_rows)
            sync_product_materials(p)
        except ValidationError as exc:
            db.session.rollback()
            flash(str(exc), "danger")
            return render_template(
                "admin/product_form.html",
                product=p,
                categories=categories,
                raw_materials=raw_materials,
                image_fit_choices=PRODUCT_IMAGE_FIT_CHOICES,
                image_position_choices=PRODUCT_IMAGE_POSITION_CHOICES,
            )
        db.session.commit()
        after_snapshot = {
            "base_price": str(p.base_price),
            "name": p.name,
            "is_active": p.is_active,
        }
        audit = get_container().audit_service
        if before_snapshot["base_price"] != after_snapshot["base_price"]:
            audit.log(
                current_user,
                "product_price_changed",
                "Product",
                p.id,
                before={"base_price": before_snapshot["base_price"]},
                after={"base_price": after_snapshot["base_price"]},
                change_summary=f"Product price updated for {p.name}",
            )
        else:
            audit.log(
                current_user,
                "product_updated",
                "Product",
                p.id,
                before=before_snapshot,
                after=after_snapshot,
                change_summary=f"Product updated: {p.name}",
            )
        for variant in p.variants.all():
            if previous_variant_stock.get(variant.id) != variant.stock:
                emit_stock_updated(variant, include_customer=True)
        flash("Product updated!", "success")
        return redirect(url_for("admin.products"))
    return render_template(
        "admin/product_form.html",
        product=p,
        categories=categories,
        raw_materials=raw_materials,
        image_fit_choices=PRODUCT_IMAGE_FIT_CHOICES,
        image_position_choices=PRODUCT_IMAGE_POSITION_CHOICES,
    )


@admin_bp.route("/products/<int:product_id>/delete", methods=["POST"])
@admin_required
@manager_required
def delete_product(product_id):
    p = db.get_or_404(Product, product_id)
    if p.is_active:
        p.is_active = False
        db.session.commit()
        flash("Product moved offline.", "info")
        return redirect(url_for("admin.products"))
    if p.total_stock <= 0:
        flash(
            "Add stock to at least one variant before making this product live.",
            "warning",
        )
        return redirect(url_for("admin.inventory"))
    p.is_active = True
    db.session.commit()
    flash("Product is live again.", "success")
    return redirect(url_for("admin.products"))


# ── ORDER MANAGEMENT ─────────────────────────────────────────
def apply_order_search(query, search):
    if not search:
        return query
    like = f"%{search}%"
    return query.filter(
        or_(
            Order.order_number.ilike(like),
            Order.phone.ilike(like),
            User.name.ilike(like),
            User.email.ilike(like),
        )
    )


@admin_bp.route("/orders")
@admin_required
@operations_required
def orders():
    status = request.args.get("status", "")
    scope = request.args.get("scope", "")
    search = (request.args.get("q") or "").strip()
    branch_id = request.args.get("branch_id", type=int)
    branch_filter = scoped_branch_or_404(branch_id) if branch_id else None
    query = scoped_order_query(
        Order.query.outerjoin(User, Order.user_id == User.id),
        include_unassigned=True,
    )
    if branch_filter:
        query = query.filter(Order.branch_id == branch_filter.id)
    if status:
        query = query.filter(Order.status == status)
    if scope == "today":
        query = query.filter(func.date(Order.placed_at) == utcnow().date())
    elif scope == "pending":
        query = query.filter(Order.status.in_(["PLACED", "PREPARING"]))
    query = apply_order_search(query, search)
    orders = query.order_by(Order.placed_at.desc()).all()
    enrich_orders(orders)
    if wants_live_fragment_response():
        return jsonify(
            {
                "fragments": {
                    "#admin-orders-live": render_template(
                        "admin/_orders_live.html",
                        orders=orders,
                    )
                }
            }
        )
    return render_template(
        "admin/orders.html",
        orders=orders,
        status_filter=status,
        scope_filter=scope,
        search=search,
        branch_filter=branch_filter,
    )


@admin_bp.route("/orders/live-past")
@admin_required
@operations_required
def live_past_orders():
    search = (request.args.get("q") or "").strip()
    base_query = scoped_order_query(
        Order.query.join(User, Order.user_id == User.id),
        include_unassigned=True,
    )
    base_query = apply_order_search(base_query, search)

    live_query = base_query.filter(Order.status.in_(LIVE_ORDER_STATUSES))
    past_query = base_query.filter(Order.status.in_(PAST_ORDER_STATUSES))

    live_orders = (
        live_query.order_by(Order.placed_at.asc(), Order.id.asc()).limit(100).all()
    )
    past_orders = (
        past_query.order_by(Order.placed_at.desc(), Order.id.desc()).limit(100).all()
    )
    enrich_orders(live_orders + past_orders)
    live_count = live_query.count()
    past_count = past_query.count()

    if wants_live_fragment_response():
        return jsonify(
            {
                "fragments": {
                    "#admin-order-monitor-live": render_template(
                        "admin/_order_monitor_live.html",
                        live_orders=live_orders,
                        past_orders=past_orders,
                        live_count=live_count,
                        past_count=past_count,
                    )
                }
            }
        )

    return render_template(
        "admin/order_monitor.html",
        live_orders=live_orders,
        past_orders=past_orders,
        live_count=live_count,
        past_count=past_count,
        search=search,
        live_statuses=LIVE_ORDER_STATUSES,
        past_statuses=PAST_ORDER_STATUSES,
    )


@admin_bp.route("/orders/<int:order_id>")
@admin_required
@operations_required
def order_detail(order_id):
    order = scoped_order_or_404(order_id, include_unassigned=True)
    items = order.items.all()
    agents = (
        scoped_agent_query(DeliveryAgent.query)
        .order_by(DeliveryAgent.availability.desc(), DeliveryAgent.name)
        .all()
    )
    mod_reqs = order.mod_requests.all()
    addr_hist = order.addr_history.all()
    payment_link = (
        PaymentLink.query.filter_by(
            order_id=order.id, purpose="ORDER", status="PENDING"
        )
        .order_by(PaymentLink.id.desc())
        .first()
    )
    qr_verification_url = url_for("api_v2.verify_qr_token", _external=True)
    order_qr_data_uri = get_container().qr_service.build_order_qr_data_uri(
        order,
        qr_verification_url,
    )
    db.session.commit()
    return render_template(
        "admin/order_detail.html",
        order=order,
        items=items,
        status_history=order.status_history.order_by(
            OrderStatusHistory.created_at.desc()
        ).limit(8).all(),
        agents=agents,
        mod_reqs=mod_reqs,
        addr_hist=addr_hist,
        payment_link=payment_link,
        allowed_statuses=get_allowed_order_statuses(order.status, actor="admin"),
        order_qr_data_uri=order_qr_data_uri,
        qr_verification_url=qr_verification_url,
    )


@admin_bp.route("/orders/<int:order_id>/update-status", methods=["POST"])
@admin_required
@operations_required
def update_order_status(order_id):
    status = (request.form.get("status") or "").strip().upper()
    scoped_order_or_404(order_id, include_unassigned=True)
    offline_sync = get_container().offline_sync_service
    if offline_sync.enabled and not offline_sync.is_online():
        snapshot = offline_sync.get_snapshot("orders", order_id) or {}
        request_id = offline_sync.queue_order_status_update_by_id(
            order_id,
            status,
            actor_id=current_user.id,
            expected_version=snapshot.get("version"),
            snapshot_payload={**snapshot, "id": order_id, "status": status},
        )
        flash(
            f"Offline mode: status change queued for sync ({request_id[:8]}).",
            "warning",
        )
        return redirect(url_for("admin.order_detail", order_id=order_id))
    try:
        expected_version = request.form.get("expected_version")
        delayed_until = None
        delayed_until_raw = (request.form.get("delayed_until") or "").strip()
        if delayed_until_raw:
            delayed_until = datetime.strptime(delayed_until_raw, "%Y-%m-%dT%H:%M")
        order = get_container().order_service.update_order_status(
            order_id,
            status,
            actor="admin",
            actor_id=current_user.id,
            expected_version=expected_version,
            customer_note=(request.form.get("customer_note") or "").strip() or None,
            internal_note=(request.form.get("internal_note") or "").strip() or None,
            delay_reason=(request.form.get("delay_reason") or "").strip() or None,
            delayed_until=delayed_until,
        )
    except ValueError:
        flash("Please choose a valid status and estimated time.", "danger")
        return redirect(url_for("admin.order_detail", order_id=order_id))
    except ValidationError as exc:
        message = str(exc) or "That status change is not allowed right now."
        flash(message, "danger")
        return redirect(url_for("admin.order_detail", order_id=order_id))
    except SQLAlchemyError:
        db.session.rollback()
        offline_sync = get_container().offline_sync_service
        snapshot = offline_sync.get_snapshot("orders", order_id) or {}
        request_id = offline_sync.queue_order_status_update_by_id(
            order_id,
            status,
            actor_id=current_user.id,
            expected_version=snapshot.get("version"),
            snapshot_payload={**snapshot, "id": order_id, "status": status},
        )
        flash(
            f"Internet unavailable. Status change queued locally for sync ({request_id[:8]}).",
            "warning",
        )
        return redirect(url_for("admin.order_detail", order_id=order_id))

    get_container().offline_sync_service.cache_order(order)

    flash(f"Order status updated to {status}.", "success")
    return redirect(url_for("admin.order_detail", order_id=order_id))


@admin_bp.route("/orders/<int:order_id>/assign-delivery", methods=["POST"])
@admin_required
@operations_required
def assign_delivery(order_id):
    order = scoped_order_or_404(order_id, include_unassigned=True)
    agent_id = request.form.get("agent_id", type=int)
    agent = scoped_agent_or_404(agent_id)
    abort_if_no_branch_access(order.branch_id, include_unassigned=True)

    expected_version = request.form.get("expected_version")
    from utils.optimistic import assert_version

    assert_version(order, expected_version, entity_name="Order")

    try:
        existing = Delivery.query.filter_by(order_id=order_id).first()
        if existing:
            existing.agent_id = agent_id
            existing.assigned_time = utcnow()
        else:
            db.session.add(
                Delivery(order_id=order_id, agent_id=agent_id, assigned_time=utcnow())
            )
        agent.availability = False
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception("delivery_assignment_failed order_id=%s", order_id)
        flash("Unable to assign delivery right now.", "danger")
        return redirect(url_for("admin.order_detail", order_id=order_id))

    deliveries = Delivery.query.filter_by(agent_id=agent_id, status="ASSIGNED").all()
    try:
        get_container().route_planning_service.plan_for_agent(agent, deliveries)
    except Exception:
        current_app.logger.exception("delivery_route_plan_failed agent_id=%s", agent_id)
    from realtime.events import emit_delivery_assignment

    emit_delivery_assignment(agent_id, order_id=order_id)
    get_container().push_service.send_to_user(
        agent.user_id,
        "New delivery assignment",
        f"Order #{order.order_number} has been assigned to you.",
        data={"order_id": order_id},
    )
    flash(f"Delivery assigned to {agent.name}.", "success")
    return redirect(url_for("admin.order_detail", order_id=order_id))


@admin_bp.route("/orders/<int:order_id>/payment-link")
@admin_required
@operations_required
def order_payment_link(order_id):
    order = scoped_order_or_404(order_id, include_unassigned=True)
    link = build_order_payment_link(order)
    # commit happens via context manager
    flash("Payment page ready.", "info")
    return redirect(url_for("customer.payment_link_page", token=link.token))


def _emit_reversal_side_effects(result):
    order = result["order"]
    reason = result.get("reason", "")
    if result["action"] == "order_refunded":
        emit_order_refunded(order, reason=reason)
    else:
        emit_order_cancelled(order, reason=reason)

    for variant_id in set(result.get("restored_variant_ids", [])):
        variant = db.session.get(ProductVariant, variant_id)
        if variant:
            emit_stock_updated(variant, include_customer=True)
    for movement in result.get("stock_movements", []):
        if movement and movement.raw_material:
            emit_stock_updated(movement.raw_material)


@admin_bp.route("/orders/<int:order_id>/cancel-refund", methods=["POST"])
@admin_required
@manager_required
def cancel_or_refund_order(order_id):
    order = scoped_order_or_404(order_id, include_unassigned=True)
    action = (request.form.get("action") or "cancel").strip().lower()
    reason = (request.form.get("reason") or "").strip()
    reverse_stock = (request.form.get("stock_handling") or "").strip() == "reverse"
    confirmed = request.form.get("confirm_reversal") == "yes"

    if not confirmed:
        flash("Please confirm the cancellation/refund before finalizing.", "warning")
        return redirect(url_for("admin.order_detail", order_id=order_id))
    if not reason:
        flash("A cancellation/refund reason is required.", "danger")
        return redirect(url_for("admin.order_detail", order_id=order_id))
    if action not in {"cancel", "refund"}:
        flash("Choose cancel or refund.", "danger")
        return redirect(url_for("admin.order_detail", order_id=order_id))

    is_paid = (order.payment_status or "").upper() == "PAID" or (
        order.payment and (order.payment.status or "").upper() == "PAID"
    )
    if is_paid and action != "refund":
        flash("Paid orders must use the refund action.", "warning")
        return redirect(url_for("admin.order_detail", order_id=order_id))
    if not is_paid and action == "refund":
        flash("This order is not paid yet; use cancel instead.", "warning")
        return redirect(url_for("admin.order_detail", order_id=order_id))

    try:
        result = get_container().order_reversal_service.cancel_or_refund_order(
            order,
            reason=reason,
            actor_id=current_user.id,
            reverse_stock=reverse_stock,
            allow_paid_refund=(action == "refund"),
            initiated_by="admin",
        )
        notify(
            order.user_id,
            (
                "Order Refunded"
                if result["action"] == "order_refunded"
                else "Order Cancelled"
            ),
            f"Order #{order.order_number} has been {order.status.lower()}.",
            "payment" if result["action"] == "order_refunded" else "order",
            url_for("customer.order_detail", order_id=order.id),
        )
        get_container().push_service.send_to_user(
            order.user_id,
            (
                "Order Refunded"
                if result["action"] == "order_refunded"
                else "Order Cancelled"
            ),
            f"Order #{order.order_number} has been {order.status.lower()}.",
            data={"order_id": order.id, "status": order.status},
        )
        db.session.commit()
        _emit_reversal_side_effects(result)
        flash(
            f"Order #{order.order_number} {order.status.lower()} successfully.",
            "success",
        )
    except ValidationError as exc:
        db.session.rollback()
        flash(str(exc), "danger")
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.exception("order_reversal_failed order_id=%s", order_id)
        flash("Unable to complete cancellation/refund right now.", "danger")
    return redirect(url_for("admin.order_detail", order_id=order_id))


# ── MODIFICATION REQUESTS ────────────────────────────────────
@admin_bp.route("/modifications")
@admin_required
@operations_required
def modifications():
    reqs = (
        ModificationRequest.query.filter_by(status="PENDING")
        .order_by(ModificationRequest.created_at.desc())
        .all()
    )
    return render_template("admin/modifications.html", reqs=reqs)


@admin_bp.route("/modifications/<int:req_id>/resolve", methods=["POST"])
@admin_required
@operations_required
def resolve_modification(req_id):
    req = db.get_or_404(ModificationRequest, req_id)
    action = request.form.get("action")
    before_status = req.status
    req.status = "APPROVED" if action == "approve" else "REJECTED"
    req.resolved_at = utcnow()
    req.order.is_locked = False

    if action == "approve":
        try:
            price_diff = float(request.form.get("price_diff", 0) or 0)
        except ValueError:
            price_diff = 0
        if price_diff > 0:
            req.order.status = "ON_HOLD"
            req.order.total += Decimal(str(price_diff))
            notify(
                req.order.user_id,
                "Extra Payment Required",
                f"Your modified order #{req.order.order_number} requires ₹{price_diff:.0f} extra.",
                "payment",
            )
        elif price_diff < 0:
            req.order.total += Decimal(str(price_diff))
            db.session.add(
                Refund(
                    order_id=req.order.id,
                    amount=abs(price_diff),
                    reason="Order modification – price reduced",
                    status="PROCESSING",
                )
            )
    db.session.commit()
    get_container().audit_service.log(
        current_user,
        "modification_request_resolved",
        "ModificationRequest",
        req.id,
        before={"status": before_status},
        after={"status": req.status, "action": action},
        change_summary=f"Modification request {req.status.lower()} for order #{req.order.order_number}",
    )
    flash("Modification request resolved.", "success")
    return redirect(url_for("admin.modifications"))


# ── REVIEWS ──────────────────────────────────────────────────
@admin_bp.route("/reviews")
@admin_required
@manager_required
def reviews():
    branch_id = request.args.get("branch_id", type=int)
    branch_filter = scoped_branch_or_404(branch_id) if branch_id else None
    query = Review.query.options(
        selectinload(Review.product),
        selectinload(Review.author),
    )
    if branch_filter:
        customer_ids = (
            db.session.query(Order.user_id)
            .filter(Order.branch_id == branch_filter.id, Order.user_id.isnot(None))
            .distinct()
        )
        query = query.filter(Review.user_id.in_(customer_ids))
    review_rows = query.order_by(Review.created_at.desc()).all()
    attention_by_id = {
        review.id: review_needs_attention(review) for review in review_rows
    }
    return render_template(
        "admin/reviews.html",
        reviews=review_rows,
        attention_by_id=attention_by_id,
        branch_filter=branch_filter,
    )


@admin_bp.route("/reviews/<int:review_id>/generate-draft", methods=["POST"])
@admin_required
@manager_required
def generate_review_draft(review_id):
    review = (
        Review.query.options(
            selectinload(Review.product),
            selectinload(Review.author),
        )
        .filter_by(id=review_id)
        .first_or_404()
    )
    payload = generate_review_reply_draft(
        review,
        current_app.config.get("BAKERY_NAME", "Sweet Crumbs Bakery"),
        current_app.config.get("STORE_DETAILS") or {},
    )
    status_code = 200 if payload.get("ok") else 503
    return jsonify(payload), status_code


@admin_bp.route("/reviews/<int:review_id>/reply", methods=["POST"])
@admin_required
@manager_required
def post_review_reply(review_id):
    review = db.get_or_404(Review, review_id)
    reply_text = (request.form.get("admin_reply") or "").strip()
    if not reply_text:
        flash("Reply cannot be empty.", "warning")
        return redirect(url_for("admin.reviews"))

    review.admin_reply = reply_text
    review.admin_reply_at = utcnow()
    db.session.commit()
    flash("Reply posted successfully.", "success")
    return redirect(url_for("admin.reviews"))


# ── CUSTOMERS ────────────────────────────────────────────────
@admin_bp.route("/customers")
@admin_required
@operations_required
def customers():
    users = (
        User.query.filter_by(role="customer")
        .order_by(User.created_at.desc())
        .all()
    )
    user_ids = [user.id for user in users]
    profiles = {
        profile.user_id: profile
        for profile in CustomerRiskProfile.query.filter(
            CustomerRiskProfile.user_id.in_(user_ids)
        ).all()
    }
    return render_template(
        "admin/customers.html", users=users, risk_profiles=profiles
    )


@admin_bp.route("/customers/<int:user_id>")
@admin_required
@operations_required
def customer_detail(user_id):
    user = db.get_or_404(User, user_id)
    orders = (
        Order.query.filter_by(user_id=user_id).order_by(Order.placed_at.desc()).all()
    )
    logins = (
        LoginHistory.query.filter_by(user_id=user_id)
        .order_by(LoginHistory.login_time.desc())
        .limit(10)
        .all()
    )
    risk = get_container().customer_risk_service.review_context(user)
    from models.customer_risk import (
        CUSTOMER_RESTRICTION_LABELS,
        CUSTOMER_RESTRICTION_TYPES,
        FLAG_REASON_LABELS,
        FLAG_REASONS,
    )

    return render_template(
        "admin/customer_detail.html",
        user=user,
        orders=orders,
        logins=logins,
        risk=risk,
        restriction_labels=CUSTOMER_RESTRICTION_LABELS,
        restriction_types=CUSTOMER_RESTRICTION_TYPES,
        flag_reasons=FLAG_REASONS,
        flag_reason_labels=FLAG_REASON_LABELS,
    )


def _risk_customer_or_404(user_id):
    customer = db.get_or_404(User, user_id)
    if (customer.role or "").strip().lower() != "customer":
        abort(404)
    return customer


def _risk_actor_id():
    return current_user.id


def _customer_redirect(user_id):
    return redirect(url_for("admin.customer_detail", user_id=user_id))


@admin_bp.route("/customers/<int:user_id>/risk/flag", methods=["POST"])
@admin_required
@operations_required
def customer_risk_flag(user_id):
    customer = _risk_customer_or_404(user_id)
    service = get_container().customer_risk_service
    try:
        service.flag(
            customer,
            actor_id=_risk_actor_id(),
            reason_category=request.form.get("reason_category", "").strip(),
            reason=request.form.get("reason", "").strip(),
            notes=request.form.get("notes", "").strip(),
            evidence=request.form.get("evidence", "").strip(),
            order_ids=_ids_from_form(request.form.get("order_ids", "")),
            payment_refs=_ids_from_form(request.form.get("payment_refs", "")),
        )
        db.session.commit()
        flash("Customer flagged for review.", "success")
    except ValidationError as exc:
        db.session.rollback()
        flash(str(exc), "danger")
    return _customer_redirect(user_id)


@admin_bp.route("/customers/<int:user_id>/risk/review", methods=["POST"])
@admin_required
@operations_required
def customer_risk_review(user_id):
    customer = _risk_customer_or_404(user_id)
    service = get_container().customer_risk_service
    action = request.form.get("action", "start_review")
    try:
        case_owner_id = request.form.get("case_owner_id", type=int) or None
        notes = request.form.get("notes", "").strip()
        if action == "start_review":
            service.start_review(
                customer,
                actor_id=_risk_actor_id(),
                case_owner_id=case_owner_id or _risk_actor_id(),
                notes=notes,
            )
        elif action == "keep_monitoring":
            service.keep_monitoring(customer, actor_id=_risk_actor_id(), notes=notes)
        elif action == "escalate":
            service.escalate(customer, actor_id=_risk_actor_id(), notes=notes)
        elif action == "clear_case":
            service.clear_case(customer, actor_id=_risk_actor_id(), notes=notes)
        else:
            raise ValidationError("Unknown review action.")
        db.session.commit()
        flash("Review status updated.", "success")
    except ValidationError as exc:
        db.session.rollback()
        flash(str(exc), "danger")
    return _customer_redirect(user_id)


@admin_bp.route("/customers/<int:user_id>/risk/restrict", methods=["POST"])
@admin_required
@operations_required
def customer_risk_restrict(user_id):
    customer = _risk_customer_or_404(user_id)
    service = get_container().customer_risk_service
    restriction_type = request.form.get("restriction_type", "").strip()
    try:
        if restriction_type == "__lift__":
            restriction_id = request.form.get("restriction_id", type=int)
            if not restriction_id:
                raise ValidationError("Choose a restriction to lift.")
            service.lift_restriction(
                customer,
                restriction_id,
                actor_id=_risk_actor_id(),
                reason=request.form.get("reason", "").strip(),
            )
        else:
            service.add_restriction(
                customer,
                restriction_type=restriction_type,
                reason=request.form.get("reason", "").strip(),
                duration_days=request.form.get("duration_days", type=int) or None,
                actor_id=_risk_actor_id(),
                notes=request.form.get("notes", "").strip(),
            )
        db.session.commit()
        flash("Restriction updated.", "success")
    except ValidationError as exc:
        db.session.rollback()
        flash(str(exc), "danger")
    return _customer_redirect(user_id)


@admin_bp.route("/customers/<int:user_id>/risk/suspend", methods=["POST"])
@admin_required
@operations_required
def customer_risk_suspend(user_id):
    customer = _risk_customer_or_404(user_id)
    service = get_container().customer_risk_service
    try:
        service.suspend(
            customer,
            actor_id=_risk_actor_id(),
            reason=request.form.get("reason", "").strip(),
            duration_days=request.form.get("duration_days", type=int) or None,
            notes=request.form.get("notes", "").strip(),
        )
        service.notify_customer(customer, actor_id=_risk_actor_id())
        db.session.commit()
        flash("Customer account suspended.", "success")
    except ValidationError as exc:
        db.session.rollback()
        flash(str(exc), "danger")
    return _customer_redirect(user_id)


@admin_bp.route("/customers/<int:user_id>/risk/restore", methods=["POST"])
@admin_required
@operations_required
def customer_risk_restore(user_id):
    customer = _risk_customer_or_404(user_id)
    service = get_container().customer_risk_service
    try:
        service.restore(
            customer,
            actor_id=_risk_actor_id(),
            reason=request.form.get("reason", "").strip(),
            notes=request.form.get("notes", "").strip(),
        )
        db.session.commit()
        flash("Customer account restored.", "success")
    except ValidationError as exc:
        db.session.rollback()
        flash(str(exc), "danger")
    return _customer_redirect(user_id)


@admin_bp.route("/customers/<int:user_id>/risk/block", methods=["POST"])
@admin_required
@manager_required
def customer_risk_block(user_id):
    customer = _risk_customer_or_404(user_id)
    service = get_container().customer_risk_service
    try:
        service.block(
            customer,
            actor_id=_risk_actor_id(),
            reason=request.form.get("reason", "").strip(),
            notes=request.form.get("notes", "").strip(),
        )
        service.notify_customer(customer, actor_id=_risk_actor_id())
        db.session.commit()
        flash("Customer account blocked.", "success")
    except ValidationError as exc:
        db.session.rollback()
        flash(str(exc), "danger")
    return _customer_redirect(user_id)


@admin_bp.route("/customers/<int:user_id>/risk/confirm-fraud", methods=["POST"])
@admin_required
@manager_required
def customer_risk_confirm_fraud(user_id):
    customer = _risk_customer_or_404(user_id)
    service = get_container().customer_risk_service
    try:
        service.confirm_fraud(
            customer,
            actor_id=_risk_actor_id(),
            reason=request.form.get("reason", "").strip(),
            notes=request.form.get("notes", "").strip(),
            evidence=request.form.get("evidence", "").strip(),
            order_ids=_ids_from_form(request.form.get("order_ids", "")),
            payment_refs=_ids_from_form(request.form.get("payment_refs", "")),
            approval_by=_risk_actor_id(),
        )
        db.session.commit()
        flash("Fraud confirmed for this customer.", "success")
    except ValidationError as exc:
        db.session.rollback()
        flash(str(exc), "danger")
    return _customer_redirect(user_id)


@admin_bp.route("/customers/<int:user_id>/risk/soft-delete", methods=["POST"])
@admin_required
@manager_required
def customer_risk_soft_delete(user_id):
    customer = _risk_customer_or_404(user_id)
    service = get_container().customer_risk_service
    try:
        service.soft_delete(
            customer,
            actor_id=_risk_actor_id(),
            reason=request.form.get("reason", "").strip(),
            notes=request.form.get("notes", "").strip(),
            confirm=request.form.get("confirm", "").strip(),
        )
        service.notify_customer(customer, actor_id=_risk_actor_id())
        db.session.commit()
        flash("Customer account soft deleted.", "success")
    except ValidationError as exc:
        db.session.rollback()
        flash(str(exc), "danger")
    return _customer_redirect(user_id)


@admin_bp.route("/customers/<int:user_id>/risk/anonymize", methods=["POST"])
@admin_required
@owner_required
def customer_risk_anonymize(user_id):
    customer = _risk_customer_or_404(user_id)
    service = get_container().customer_risk_service
    try:
        service.anonymize(
            customer,
            actor_id=_risk_actor_id(),
            reason=request.form.get("reason", "").strip(),
            notes=request.form.get("notes", "").strip(),
            approval_by=_risk_actor_id(),
        )
        db.session.commit()
        flash("Customer data anonymized.", "success")
    except ValidationError as exc:
        db.session.rollback()
        flash(str(exc), "danger")
    return _customer_redirect(user_id)


@admin_bp.route("/customers/<int:user_id>/risk/delete", methods=["POST"])
@admin_required
@owner_required
def customer_risk_delete(user_id):
    customer = _risk_customer_or_404(user_id)
    service = get_container().customer_risk_service
    try:
        service.delete_permanently(
            customer,
            actor_id=_risk_actor_id(),
            reason=request.form.get("reason", "").strip(),
            notes=request.form.get("notes", "").strip(),
            confirm=request.form.get("confirm", "").strip(),
            approval_by=_risk_actor_id(),
        )
        db.session.commit()
        flash("Customer permanently deleted.", "success")
    except ValidationError as exc:
        db.session.rollback()
        flash(str(exc), "danger")
    return _customer_redirect(user_id)


def _ids_from_form(raw):
    return [token for token in (raw or "").replace(",", " ").split() if token.strip()]


@admin_bp.route("/blocklist")
@admin_required
@operations_required
def blocklist():
    from models.customer_risk import (
        BLOCKLIST_IDENTIFIER_TYPES,
        BLOCKLIST_STATUSES,
    )

    entries = FraudBlocklistEntry.query.order_by(
        FraudBlocklistEntry.created_at.desc()
    ).all()
    return render_template(
        "admin/blocklist.html",
        entries=entries,
        identifier_types=BLOCKLIST_IDENTIFIER_TYPES,
        blocklist_statuses=BLOCKLIST_STATUSES,
    )


@admin_bp.route("/blocklist/add", methods=["POST"])
@admin_required
@operations_required
def blocklist_add():
    service = get_container().customer_risk_service
    try:
        service.add_blocklist(
            identifier_type=request.form.get("identifier_type", "").strip(),
            identifier_value=request.form.get("identifier_value", "").strip(),
            reason=request.form.get("reason", "").strip(),
            case_user_id=request.form.get("case_user_id", type=int) or None,
            actor_id=_risk_actor_id(),
            auto_approve=request.form.get("auto_approve") == "1",
        )
        db.session.commit()
        flash("Identifier added to the blocklist.", "success")
    except ValidationError as exc:
        db.session.rollback()
        flash(str(exc), "danger")
    return redirect(url_for("admin.blocklist"))


@admin_bp.route("/blocklist/<int:entry_id>/review", methods=["POST"])
@admin_required
@manager_required
def blocklist_review(entry_id):
    service = get_container().customer_risk_service
    try:
        service.review_blocklist(
            entry_id,
            status=request.form.get("status", "").strip(),
            review_notes=request.form.get("review_notes", "").strip(),
            actor_id=_risk_actor_id(),
        )
        db.session.commit()
        flash("Blocklist review updated.", "success")
    except ValidationError as exc:
        db.session.rollback()
        flash(str(exc), "danger")
    return redirect(url_for("admin.blocklist"))


# ── CUSTOMER SUPPORT ─────────────────────────────────────────
@admin_bp.route("/support")
@admin_bp.route("/chat")
@admin_required
@operations_required
def chat():
    support_threads = support_thread_summaries()
    return render_template(
        "admin/chat.html",
        support_threads=support_threads,
        support_staff=support_staff_members(),
    )


@admin_bp.route("/support/<int:customer_id>")
@admin_bp.route("/chat/<int:customer_id>")
@admin_required
@operations_required
def chat_thread(customer_id):
    customer = db.get_or_404(User, customer_id)
    if customer.role != "customer":
        abort(404)
    messages = support_thread_messages(customer_id)
    staff_ids = support_staff_ids()
    Message.query.filter(
        Message.receiver_id.in_(staff_ids),
        Message.sender_id == customer_id,
        Message.is_read.is_(False),
    ).update({"is_read": True}, synchronize_session=False)
    db.session.commit()
    support_threads = support_thread_summaries(active_customer_id=customer_id)
    return render_template(
        "admin/chat.html",
        support_threads=support_threads,
        support_staff=support_staff_members(),
        messages=messages,
        active_customer=customer,
    )


@admin_bp.route("/chat/send/<int:receiver_id>", methods=["POST"])
@admin_required
@operations_required
def admin_send_message(receiver_id):
    content = request.form.get("content", "").strip()
    customer = db.get_or_404(User, receiver_id)
    if customer.role != "customer":
        abort(404)
    if content:
        message = Message(
            sender_id=current_user.id,
            receiver_id=receiver_id,
            content=content,
        )
        db.session.add(message)
        db.session.flush()
        notify(
            receiver_id,
            "New Support Message",
            content[:100],
            "chat",
            url_for("customer.chat"),
        )
        db.session.commit()
        emit_support_message(message, receiver_id)
    return redirect(url_for("admin.chat_thread", customer_id=receiver_id))


INVENTORY_SALES_PERIODS = ("today", "week", "month", "year")
INVENTORY_PERIOD_LABELS = {
    "today": "Day",
    "week": "Week",
    "month": "Month",
    "year": "Year",
}
INVENTORY_SALES_STATUSES = ("DELIVERED",)
INVENTORY_SALES_PAYMENT_STATUSES = ("PAID",)


def _sales_period_totals(product_ids):
    if not product_ids:
        return {}

    totals = {
        product_id: {period: 0 for period in INVENTORY_SALES_PERIODS}
        for product_id in product_ids
    }
    for period in INVENTORY_SALES_PERIODS:
        start, end = period_bounds(period)
        rows = (
            db.session.query(
                OrderItem.product_id,
                func.coalesce(func.sum(OrderItem.quantity), 0).label("units"),
            )
            .join(Order, Order.id == OrderItem.order_id)
            .filter(
                OrderItem.product_id.in_(product_ids),
                Order.status.in_(INVENTORY_SALES_STATUSES),
                Order.payment_status.in_(INVENTORY_SALES_PAYMENT_STATUSES),
                Order.placed_at >= start,
                Order.placed_at < end,
            )
            .group_by(OrderItem.product_id)
            .all()
        )
        for product_id, units in rows:
            totals.setdefault(product_id, {})[period] = int(units or 0)
    return totals


def _best_branch_by_product(product_ids):
    if not product_ids:
        return {}

    start, end = period_bounds("year")
    rows = (
        db.session.query(
            OrderItem.product_id,
            Order.branch_id,
            Branch.name.label("branch_name"),
            func.coalesce(func.sum(OrderItem.quantity), 0).label("units"),
            func.coalesce(func.sum(OrderItem.subtotal), 0).label("revenue"),
        )
        .join(Order, Order.id == OrderItem.order_id)
        .outerjoin(Branch, Branch.id == Order.branch_id)
        .filter(
            OrderItem.product_id.in_(product_ids),
            Order.status.in_(INVENTORY_SALES_STATUSES),
            Order.payment_status.in_(INVENTORY_SALES_PAYMENT_STATUSES),
            Order.placed_at >= start,
            Order.placed_at < end,
        )
        .group_by(OrderItem.product_id, Order.branch_id, Branch.name)
        .order_by(OrderItem.product_id.asc(), func.sum(OrderItem.quantity).desc())
        .all()
    )

    best_by_product = {}
    for row in rows:
        if row.product_id in best_by_product:
            continue
        best_by_product[row.product_id] = {
            "name": row.branch_name or "Unassigned branch",
            "units": int(row.units or 0),
            "revenue": float(row.revenue or 0),
        }
    return best_by_product


def _serialize_product_materials(product):
    material_rows = []
    producible_limits = []
    for recipe_item in product.recipe_items.order_by(ProductMaterial.id.asc()).all():
        material = recipe_item.raw_material
        required = Decimal(str(recipe_item.quantity_required or 0))
        stock = Decimal(str(material.stock if material else 0))
        can_make = None
        if required > 0:
            can_make = int(stock // required)
            producible_limits.append(can_make)
        material_rows.append(
            {
                "name": material.name if material else "Missing material",
                "unit": material.unit if material else "",
                "required": required,
                "stock": stock,
                "status": material.stock_status if material else "out_of_stock",
                "can_make": can_make,
            }
        )

    if not material_rows:
        recipe_status = "not_configured"
    elif any(item["status"] == "out_of_stock" for item in material_rows):
        recipe_status = "out_of_stock"
    elif any(item["status"] == "low_stock" for item in material_rows):
        recipe_status = "low_stock"
    else:
        recipe_status = "ready"

    return {
        "items": material_rows,
        "recipe_status": recipe_status,
        "producible_units": min(producible_limits) if producible_limits else None,
    }


def _build_product_inventory_cards(variants):
    grouped = {}
    for variant in variants:
        if not variant.product:
            continue
        grouped.setdefault(variant.product_id, {"product": variant.product, "variants": []})
        grouped[variant.product_id]["variants"].append(variant)

    product_ids = list(grouped.keys())
    sales_totals = _sales_period_totals(product_ids)
    best_branches = _best_branch_by_product(product_ids)

    cards = []
    for product_id, payload in grouped.items():
        product = payload["product"]
        material_payload = _serialize_product_materials(product)
        cards.append(
            {
                "product": product,
                "variants": payload["variants"],
                "sales": sales_totals.get(
                    product_id,
                    {period: 0 for period in INVENTORY_SALES_PERIODS},
                ),
                "best_branch": best_branches.get(product_id),
                "materials": material_payload["items"],
                "recipe_status": material_payload["recipe_status"],
                "producible_units": material_payload["producible_units"],
            }
        )
    return cards


def _latest_material_receipts(material_ids):
    if not material_ids:
        return {}
    rows = (
        db.session.query(
            PurchaseOrderItem.raw_material_id,
            PurchaseOrder.id.label("purchase_order_id"),
            PurchaseOrder.received_at,
            PurchaseOrder.order_date,
            PurchaseOrderItem.quantity,
            PurchaseOrderItem.unit_cost,
            Vendor.name.label("vendor_name"),
        )
        .join(PurchaseOrder, PurchaseOrder.id == PurchaseOrderItem.purchase_order_id)
        .join(Vendor, Vendor.id == PurchaseOrder.vendor_id)
        .filter(
            PurchaseOrderItem.raw_material_id.in_(material_ids),
            PurchaseOrder.status == "received",
        )
        .order_by(PurchaseOrder.received_at.desc(), PurchaseOrder.id.desc())
        .all()
    )

    latest = {}
    for row in rows:
        if row.raw_material_id in latest:
            continue
        latest[row.raw_material_id] = {
            "purchase_order_id": row.purchase_order_id,
            "received_at": row.received_at,
            "order_date": row.order_date,
            "quantity": row.quantity,
            "unit_cost": row.unit_cost,
            "vendor_name": row.vendor_name,
        }
    return latest


def _build_raw_material_inventory_cards(materials):
    material_ids = [material.id for material in materials]
    latest_receipts = _latest_material_receipts(material_ids)
    cards = []
    for material in materials:
        vendor_links = material.vendor_products.order_by(VendorProduct.updated_at.desc()).all()
        movement = material.stock_movements.order_by(StockMovement.created_at.desc()).first()
        cards.append(
            {
                "material": material,
                "vendors": vendor_links,
                "last_receipt": latest_receipts.get(material.id),
                "last_movement": movement,
            }
        )
    return cards


# ── INVENTORY ────────────────────────────────────────────────
@admin_bp.route("/inventory")
@admin_required
@operations_required
def inventory():
    get_container().inventory_service.backfill_missing_product_variants()
    variants = (
        scoped_variant_query(ProductVariant.query.join(Product))
        .filter(Product.is_active.is_(True))
        .order_by(Product.is_active.desc(), ProductVariant.stock.asc(), Product.name)
        .all()
    )
    materials = scoped_material_query(RawMaterial.query).order_by(
        RawMaterial.is_active.desc(), RawMaterial.stock.asc(), RawMaterial.name
    ).all()
    live_products = Product.query.filter_by(is_active=True).count()
    inactive_products = Product.query.filter_by(is_active=False).count()
    low_variant_count = scoped_variant_query(
        ProductVariant.query.filter(ProductVariant.stock > 0, ProductVariant.stock <= 5)
    ).count()
    out_of_stock_count = scoped_variant_query(
        ProductVariant.query.filter_by(stock=0)
    ).count()
    raw_material_alerts = scoped_material_query(
        RawMaterial.query.filter(
            RawMaterial.is_active == True,
            RawMaterial.stock <= RawMaterial.reorder_level,
        )
    ).count()
    product_inventory_cards = _build_product_inventory_cards(variants)
    raw_material_inventory_cards = _build_raw_material_inventory_cards(materials)
    return render_template(
        "admin/inventory.html",
        variants=variants,
        materials=materials,
        product_inventory_cards=product_inventory_cards,
        raw_material_inventory_cards=raw_material_inventory_cards,
        inventory_periods=INVENTORY_SALES_PERIODS,
        inventory_period_labels=INVENTORY_PERIOD_LABELS,
        live_products=live_products,
        inactive_products=inactive_products,
        low_variant_count=low_variant_count,
        out_of_stock_count=out_of_stock_count,
        raw_material_alerts=raw_material_alerts,
    )


@admin_bp.route("/inventory/update", methods=["POST"])
@admin_required
@operations_required
def update_stock():
    variant_id = request.form.get("variant_id", type=int)
    try:
        v = scoped_variant_or_404(variant_id)
    except SQLAlchemyError:
        v = None
    new_stock = request.form.get("stock", type=int)
    offline_sync = get_container().offline_sync_service
    if offline_sync.enabled and not offline_sync.is_online():
        snapshot = offline_sync.get_snapshot("variants", variant_id) or {}
        request_id = offline_sync.queue_variant_stock_update_by_id(
            variant_id,
            new_stock,
            actor_id=current_user.id,
            expected_version=snapshot.get("version"),
            snapshot_payload={**snapshot, "id": variant_id, "stock": new_stock},
        )
        flash(
            f"Offline mode: stock update queued for sync ({request_id[:8]}).",
            "warning",
        )
        return redirect(url_for("admin.inventory"))
    try:
        if v is None:
            raise SQLAlchemyError("Database unavailable")
        expected_version = request.form.get("expected_version")
        from utils.optimistic import assert_version

        assert_version(v, expected_version, entity_name="ProductVariant")
        previous_stock = v.stock
        v.stock = new_stock
        v.version = int(v.version or 0) + 1
        get_container().audit_service.log(
            current_user,
            "stock_adjusted",
            "ProductVariant",
            v.id,
            before={"stock": previous_stock},
            after={"stock": new_stock},
            change_summary=f"Variant stock set to {new_stock}",
        )
        db.session.commit()
        get_container().offline_sync_service.cache_variant(v)
        emit_stock_updated(v, include_customer=True)
        try:
            check_and_send_inventory_alerts()
        except Exception:
            pass
        flash("Stock updated!", "success")
    except SQLAlchemyError:
        db.session.rollback()
        offline_sync = get_container().offline_sync_service
        snapshot = offline_sync.get_snapshot("variants", variant_id) or {}
        request_id = offline_sync.queue_variant_stock_update_by_id(
            variant_id,
            new_stock,
            actor_id=current_user.id,
            expected_version=snapshot.get("version"),
            snapshot_payload={**snapshot, "id": variant_id, "stock": new_stock},
        )
        flash(
            f"Internet unavailable. Stock update queued locally for sync ({request_id[:8]}).",
            "warning",
        )
    return redirect(url_for("admin.inventory"))


@admin_bp.route("/inventory/raw-material/update", methods=["POST"])
@admin_required
@operations_required
def update_raw_material_stock():
    material_id = request.form.get("material_id", type=int)
    try:
        mat = scoped_material_or_404(material_id)
    except SQLAlchemyError:
        mat = None
    try:
        new_stock = parse_decimal(request.form.get("stock"), "stock")
    except ValueError as e:
        flash(str(e), "danger")
        return redirect(url_for("admin.inventory"))
    offline_sync = get_container().offline_sync_service
    if offline_sync.enabled and not offline_sync.is_online():
        snapshot = offline_sync.get_snapshot("raw_materials", material_id) or {}
        request_id = offline_sync.queue_material_stock_update_by_id(
            material_id,
            new_stock,
            actor_id=current_user.id,
            expected_version=snapshot.get("version"),
            snapshot_payload={**snapshot, "id": material_id, "stock": float(new_stock)},
        )
        flash(
            f"Offline mode: material update queued for sync ({request_id[:8]}).",
            "warning",
        )
        return redirect(url_for("admin.inventory"))
    try:
        if mat is None:
            raise SQLAlchemyError("Database unavailable")
        expected_version = request.form.get("expected_version")
        from utils.optimistic import assert_version

        assert_version(mat, expected_version, entity_name="RawMaterial")
        previous_stock = Decimal(str(mat.stock or 0))
        inventory_service = get_container().inventory_service
        if new_stock > previous_stock:
            movement = inventory_service.increase_raw_material_stock(
                mat,
                new_stock - previous_stock,
                reason="manual_restock",
                created_by=current_user.id,
            )
        elif new_stock != previous_stock:
            movement = inventory_service.set_raw_material_stock(
                mat,
                new_stock,
                reason="correction",
                created_by=current_user.id,
            )
        else:
            movement = None
        db.session.commit()
        get_container().offline_sync_service.cache_material(mat)
        try:
            check_and_send_inventory_alerts()
        except Exception:
            pass
        if (
            movement
            and Decimal(str(movement.change_amount or 0)) > 0
            and movement.reason == "manual_restock"
        ):
            flash(
                "Raw material restocked. Log the purchase expense when ready.", "info"
            )
            return redirect(
                url_for("admin.finance_log_restock", movement_id=movement.id)
            )
        flash("Raw material stock updated!", "success")
    except SQLAlchemyError:
        db.session.rollback()
        offline_sync = get_container().offline_sync_service
        snapshot = offline_sync.get_snapshot("raw_materials", material_id) or {}
        request_id = offline_sync.queue_material_stock_update_by_id(
            material_id,
            new_stock,
            actor_id=current_user.id,
            expected_version=snapshot.get("version"),
            snapshot_payload={**snapshot, "id": material_id, "stock": float(new_stock)},
        )
        flash(
            f"Internet unavailable. Material update queued locally for sync ({request_id[:8]}).",
            "warning",
        )
    return redirect(url_for("admin.inventory"))


def _branch_detail_summary(branch):
    realized_total = Order.total + func.coalesce(Order.gift_card_redemption_amount, 0)
    active_order_filter = (
        Order.branch_id == branch.id,
        Order.status != "CANCELLED",
    )
    now = utcnow()
    today_start = datetime.combine(now.date(), time.min)
    week_start = today_start - timedelta(days=today_start.weekday())
    month_start = today_start.replace(day=1)
    year_start = today_start.replace(month=1, day=1)

    def sales_since(start_at):
        return Decimal(
            str(
                db.session.query(func.coalesce(func.sum(realized_total), 0))
                .filter(*active_order_filter, Order.placed_at >= start_at)
                .scalar()
                or 0
            )
        )

    order_count = Order.query.filter(*active_order_filter).count()
    total_sales = (
        db.session.query(func.coalesce(func.sum(realized_total), 0))
        .filter(*active_order_filter)
        .scalar()
        or Decimal("0")
    )
    last_30_days = now - timedelta(days=30)
    recent_sales = (
        db.session.query(func.coalesce(func.sum(realized_total), 0))
        .filter(
            *active_order_filter,
            Order.placed_at >= last_30_days,
        )
        .scalar()
        or Decimal("0")
    )
    customer_count = (
        db.session.query(func.count(func.distinct(Order.user_id)))
        .filter(*active_order_filter)
        .scalar()
        or 0
    )
    recent_orders = (
        Order.query.options(selectinload(Order.customer))
        .filter(*active_order_filter)
        .order_by(Order.placed_at.desc())
        .limit(4)
        .all()
    )
    employees = (
        User.query.filter(
            User.branch_id == branch.id,
            User.role.in_(tuple(BRANCH_EMPLOYEE_ROLE_VALUES)),
        )
        .order_by(User.role.asc(), User.name.asc())
        .all()
    )
    annotate_staff_access(employees)
    delivery_agents = (
        DeliveryAgent.query.options(selectinload(DeliveryAgent.user))
        .filter(DeliveryAgent.branch_id == branch.id)
        .order_by(DeliveryAgent.availability.desc(), DeliveryAgent.name.asc())
        .all()
    )
    customer_ids = [
        row[0]
        for row in db.session.query(Order.user_id)
        .filter(*active_order_filter, Order.user_id.isnot(None))
        .distinct()
        .all()
    ]
    review_count = 0
    average_rating = None
    recent_reviews = []
    if customer_ids:
        review_filter = Review.user_id.in_(customer_ids)
        review_count = Review.query.filter(review_filter).count()
        average_rating = (
            db.session.query(func.avg(Review.rating)).filter(review_filter).scalar()
        )
        recent_reviews = (
            Review.query.options(selectinload(Review.product), selectinload(Review.author))
            .filter(review_filter)
            .order_by(Review.created_at.desc())
            .limit(3)
            .all()
        )
    total_sales_decimal = Decimal(str(total_sales or 0))
    return {
        "order_count": order_count,
        "total_sales": total_sales_decimal,
        "recent_sales": Decimal(str(recent_sales or 0)),
        "sales_periods": [
            ("Today", sales_since(today_start)),
            ("This Week", sales_since(week_start)),
            ("This Month", sales_since(month_start)),
            ("This Year", sales_since(year_start)),
        ],
        "customer_count": customer_count,
        "avg_order": (
            total_sales_decimal / Decimal(order_count)
            if order_count
            else Decimal("0")
        ),
        "recent_orders": recent_orders,
        "employees": employees,
        "delivery_agents": delivery_agents,
        "raw_material_count": RawMaterial.query.filter_by(branch_id=branch.id).count(),
        "open_delivery_count": Delivery.query.filter(
            Delivery.branch_id == branch.id,
            Delivery.status != "DELIVERED",
        ).count(),
        "review_count": review_count,
        "average_rating": average_rating,
        "recent_reviews": recent_reviews,
    }


def _supplier_detail_summary(supplier):
    materials = (
        RawMaterial.query.filter(func.lower(RawMaterial.supplier) == supplier.name.lower())
        .order_by(RawMaterial.name.asc())
        .all()
    )
    material_ids = [material.id for material in materials]
    last_movement = None
    if material_ids:
        last_movement = (
            StockMovement.query.filter(StockMovement.raw_material_id.in_(material_ids))
            .order_by(StockMovement.created_at.desc())
            .first()
        )
    vendor = Vendor.query.filter(func.lower(Vendor.name) == supplier.name.lower()).first()
    purchase_orders = []
    purchase_count = 0
    total_spend = Decimal("0")
    last_received = None
    if vendor:
        purchase_orders = (
            PurchaseOrder.query.filter_by(vendor_id=vendor.id)
            .order_by(PurchaseOrder.order_date.desc(), PurchaseOrder.id.desc())
            .limit(4)
            .all()
        )
        purchase_count = PurchaseOrder.query.filter_by(vendor_id=vendor.id).count()
        total_spend = (
            db.session.query(
                func.coalesce(
                    func.sum(PurchaseOrderItem.quantity * PurchaseOrderItem.unit_cost),
                    0,
                )
            )
            .join(PurchaseOrder, PurchaseOrder.id == PurchaseOrderItem.purchase_order_id)
            .filter(PurchaseOrder.vendor_id == vendor.id)
            .scalar()
            or Decimal("0")
        )
        last_received = (
            db.session.query(func.max(PurchaseOrder.received_at))
            .filter(
                PurchaseOrder.vendor_id == vendor.id,
                PurchaseOrder.status == "received",
            )
            .scalar()
        )
    return {
        "materials": materials,
        "material_count": len(materials),
        "low_stock_count": sum(
            1 for material in materials if material.stock_status != "in_stock"
        ),
        "last_movement": last_movement,
        "vendor": vendor,
        "purchase_orders": purchase_orders,
        "purchase_count": purchase_count,
        "total_spend": Decimal(str(total_spend or 0)),
        "last_received": last_received,
    }


@admin_bp.route("/suppliers")
@admin_required
@manager_required
def suppliers():
    search = (request.args.get("q") or "").strip()
    query = Supplier.query
    if search:
        query = query.filter(Supplier.name.ilike(f"%{search}%"))
    suppliers = query.order_by(Supplier.is_active.desc(), Supplier.name).all()
    for supplier in suppliers:
        supplier.detail_summary = _supplier_detail_summary(supplier)
    return render_template("admin/suppliers.html", suppliers=suppliers, search=search)


@admin_bp.route("/suppliers/add", methods=["POST"])
@admin_required
@manager_required
def add_supplier():
    name = (request.form.get("name") or "").strip()
    if not name:
        flash("Supplier name is required.", "danger")
        return redirect(url_for("admin.suppliers"))
    if Supplier.query.filter(func.lower(Supplier.name) == name.lower()).first():
        flash("Supplier already exists.", "warning")
        return redirect(url_for("admin.suppliers"))
    supplier = Supplier(
        name=name,
        contact_name=(request.form.get("contact_name") or "").strip(),
        email=(request.form.get("email") or "").strip(),
        phone=(request.form.get("phone") or "").strip(),
        address=(request.form.get("address") or "").strip(),
        payment_terms=(request.form.get("payment_terms") or "").strip(),
        notes=(request.form.get("notes") or "").strip(),
    )
    db.session.add(supplier)
    db.session.commit()
    flash("Supplier added successfully.", "success")
    return redirect(url_for("admin.suppliers"))


@admin_bp.route("/suppliers/<int:supplier_id>/toggle", methods=["POST"])
@admin_required
@manager_required
def toggle_supplier_status(supplier_id):
    supplier = db.get_or_404(Supplier, supplier_id)
    supplier.is_active = not supplier.is_active
    db.session.commit()
    flash(
        f"Supplier {'activated' if supplier.is_active else 'paused'}.",
        "success" if supplier.is_active else "info",
    )
    return redirect(url_for("admin.suppliers"))


@admin_bp.route("/delivery-cash")
@admin_required
@manager_required
def delivery_cash_ledger():
    agents = (
        scoped_agent_query(
            DeliveryAgent.query.options(
                selectinload(DeliveryAgent.user),
                selectinload(DeliveryAgent.branch),
            )
        )
        .order_by(DeliveryAgent.name.asc())
        .all()
    )
    selected_agent_id = request.args.get("agent_id", type=int)
    accessible_agent_ids = {agent.id for agent in agents}
    if selected_agent_id and selected_agent_id not in accessible_agent_ids:
        abort(403)
    balances = get_container().delivery_cash_service.agent_balances(
        [agent.id for agent in agents]
    )
    ledger_query = (
        DeliveryCashLedger.query.options(
            selectinload(DeliveryCashLedger.agent),
            selectinload(DeliveryCashLedger.order),
            selectinload(DeliveryCashLedger.recorder),
        )
        .join(DeliveryAgent, DeliveryAgent.id == DeliveryCashLedger.agent_id)
    )
    ledger_query = scope_query_to_admin_branch(
        ledger_query,
        DeliveryAgent.branch_id,
        include_unassigned=False,
    )
    if selected_agent_id:
        ledger_query = ledger_query.filter(DeliveryCashLedger.agent_id == selected_agent_id)
    entries = (
        ledger_query.order_by(
            DeliveryCashLedger.created_at.desc(),
            DeliveryCashLedger.id.desc(),
        )
        .limit(250)
        .all()
    )
    total_outstanding = sum(balances.values(), Decimal("0.00"))
    return render_template(
        "admin/delivery_cash_ledger.html",
        agents=agents,
        balances=balances,
        entries=entries,
        selected_agent_id=selected_agent_id,
        total_outstanding=total_outstanding,
    )


@admin_bp.route("/delivery-cash/<int:agent_id>/handover", methods=["POST"])
@admin_required
@manager_required
def delivery_cash_handover(agent_id):
    agent = scoped_agent_or_404(agent_id)
    try:
        get_container().delivery_cash_service.record_handover(
            agent_id=agent.id,
            amount=request.form.get("amount"),
            actor_id=current_user.id,
            notes=request.form.get("notes", ""),
        )
        db.session.commit()
        flash(f"Cash handover recorded for {agent.name}.", "success")
    except ValidationError as exc:
        db.session.rollback()
        flash(str(exc), "danger")
    return redirect(url_for("admin.delivery_cash_ledger", agent_id=agent.id))


@admin_bp.route("/delivery-cash/<int:agent_id>/recover", methods=["POST"])
@admin_required
@manager_required
def delivery_cash_recover(agent_id):
    agent = scoped_agent_or_404(agent_id)
    try:
        get_container().delivery_cash_service.record_recovery(
            agent=agent,
            amount=request.form.get("amount"),
            recovery_method=request.form.get("recovery_method"),
            actor_id=current_user.id,
            notes=request.form.get("notes", ""),
        )
        db.session.commit()
        flash(f"Cash shortage recovery recorded for {agent.name}.", "success")
    except ValidationError as exc:
        db.session.rollback()
        flash(str(exc), "danger")
    return redirect(url_for("admin.delivery_cash_ledger", agent_id=agent.id))

def normalize_vendor_payment_method(value):
    method = (value or "").strip().upper()
    return method if method in VENDOR_PAYMENT_METHOD_LABELS else ""


def vendor_payment_method_label(value):
    method = normalize_vendor_payment_method(value)
    return VENDOR_PAYMENT_METHOD_LABELS.get(method, "")


def mask_payment_reference(value):
    reference = (value or "").strip()
    if not reference:
        return ""
    if len(reference) <= 4:
        return "****"
    return f"****{reference[-4:]}"


def normalize_tds_payment_type(value):
    payment_type = (value or "").strip().lower()
    return payment_type if payment_type in TDS_PAYMENT_TYPE_VALUES else TDS_PAYMENT_TYPE_NONE


def optional_vendor_decimal(field_name, label):
    raw_value = (request.form.get(field_name) or "").strip()
    if not raw_value:
        return None
    value = parse_decimal(raw_value, label)
    if value < 0:
        raise ValueError(f"{label} cannot be negative.")
    return value


def apply_vendor_tds_form(vendor):
    vendor.pan = (request.form.get("pan") or "").strip().upper() or None
    vendor.tds_enabled = bool(request.form.get("tds_enabled"))
    vendor.tds_payment_type = normalize_tds_payment_type(
        request.form.get("tds_payment_type")
    )
    vendor.tds_rate_percent = optional_vendor_decimal(
        "tds_rate_percent", "TDS rate"
    )
    vendor.tds_threshold_amount = optional_vendor_decimal(
        "tds_threshold_amount", "TDS annual threshold"
    )
    vendor.tds_notes = (request.form.get("tds_notes") or "").strip() or None


def purchase_order_due_generated_at(purchase_order):
    if purchase_order.created_at:
        return purchase_order.created_at
    if purchase_order.order_date:
        return datetime.combine(purchase_order.order_date, time.min)
    return None


def vendor_payment_history(vendor, purchase_orders):
    transactions = (
        FinancialTransaction.query.filter_by(vendor_id=vendor.id)
        .order_by(FinancialTransaction.created_at.asc(), FinancialTransaction.id.asc())
        .all()
    )
    transactions_by_po = {}
    for txn in transactions:
        if not txn.reference_purchase_order_id:
            continue
        transactions_by_po.setdefault(txn.reference_purchase_order_id, []).append(txn)
    rows = []
    linked_transaction_ids = set()
    for po in purchase_orders:
        payments = transactions_by_po.get(po.id, [])
        for payment in payments:
            linked_transaction_ids.add(payment.id)
        txn = payments[-1] if payments else None
        paid_amount = sum(
            (Decimal(str(payment.amount or 0)) for payment in payments),
            Decimal("0"),
        )
        total_amount = Decimal(str(po.subtotal or 0))
        remaining_amount = max(Decimal("0"), total_amount - paid_amount)
        tds_withheld = txn.tds_withheld if txn else po.tds_amount
        tds_withheld = Decimal(str(tds_withheld or 0))
        tds_status = "Not applicable"
        if tds_withheld > 0:
            tds_status = "Deposited" if po.tds_deposited_at else "Pending deposit"
        po_status = (po.status or "").strip().lower()
        if po_status == "cancelled":
            payment_status = "Cancelled"
        elif paid_amount >= total_amount:
            payment_status = "Paid"
        elif paid_amount > 0:
            payment_status = "Partially Paid"
        else:
            payment_status = "Due"
        rows.append(
            {
                "purchase_order": po,
                "transaction": txn,
                "payments": payments,
                "paid_amount": paid_amount,
                "remaining_amount": remaining_amount,
                "amount": total_amount,
                "tds_withheld": tds_withheld,
                "tds_section": po.tds_section or vendor.tds_section,
                "tds_deposit_due_date": po.tds_deposit_due_date,
                "tds_status": tds_status,
                "due_generated_at": purchase_order_due_generated_at(po),
                "due_date": po.expected_delivery_date or po.order_date,
                "paid_at": txn.created_at if txn else None,
                "payment_method": txn.payment_method if txn else "",
                "payment_method_label": vendor_payment_method_label(
                    txn.payment_method if txn else ""
                ),
                "status": payment_status,
            }
        )

    for txn in transactions:
        if txn.id in linked_transaction_ids:
            continue
        tds_withheld = Decimal(str(txn.tds_withheld or 0))
        rows.append(
            {
                "purchase_order": txn.purchase_order,
                "transaction": txn,
                "payments": [txn],
                "paid_amount": Decimal(str(txn.amount or 0)),
                "remaining_amount": Decimal("0"),
                "amount": txn.amount,
                "tds_withheld": tds_withheld,
                "tds_section": vendor.tds_section if tds_withheld > 0 else "",
                "tds_deposit_due_date": (
                    get_container().finance_service.tds_deposit_due_date(txn.created_at)
                    if tds_withheld > 0
                    else None
                ),
                "tds_status": "Pending deposit" if tds_withheld > 0 else "Not applicable",
                "due_generated_at": txn.created_at,
                "due_date": None,
                "paid_at": txn.created_at,
                "payment_method": txn.payment_method,
                "payment_method_label": vendor_payment_method_label(
                    txn.payment_method
                ),
                "status": "Paid",
            }
        )

    return sorted(
        rows,
        key=lambda row: row["paid_at"] or row["due_generated_at"] or datetime.min,
        reverse=True,
    )


PURCHASE_ORDER_UPDATE_LABELS = {
    "purchase_order_placed": "Purchase order placed",
    "purchase_order_ordered": "Marked ordered",
    "purchase_order_cancelled": "Cancelled",
    "purchase_order_received": "Received",
}


def purchase_order_update_badge(action):
    return {
        "purchase_order_received": "badge-green",
        "purchase_order_cancelled": "badge-red",
        "purchase_order_ordered": "badge-blue",
        "payment_recorded": "badge-green",
    }.get(action, "badge-brown")


def purchase_order_audits(purchase_order_ids):
    ids = [str(po_id) for po_id in purchase_order_ids]
    if not ids:
        return {}
    logs = (
        AuditLog.query.filter(
            AuditLog.entity_type == "PurchaseOrder",
            AuditLog.entity_id.in_(ids),
        )
        .order_by(AuditLog.created_at.asc(), AuditLog.id.asc())
        .all()
    )
    grouped = {}
    for log in logs:
        grouped.setdefault(int(log.entity_id), []).append(log)
    return grouped


def purchase_order_transaction_map(purchase_order_ids):
    ids = list(purchase_order_ids)
    if not ids:
        return {}
    transactions = (
        FinancialTransaction.query.filter(
            FinancialTransaction.reference_purchase_order_id.in_(ids)
        )
        .order_by(FinancialTransaction.created_at.asc(), FinancialTransaction.id.asc())
        .all()
    )
    rows = {}
    for transaction in transactions:
        rows.setdefault(transaction.reference_purchase_order_id, []).append(transaction)
    return rows


def log_purchase_order_update(purchase_order, action, actor_id, summary, before=None, after=None):
    try:
        get_container().audit_service.log(
            actor_id,
            action,
            "PurchaseOrder",
            purchase_order.id,
            before=before,
            after=after,
            change_summary=summary,
        )
    except Exception:
        current_app.logger.exception("purchase_order_audit_failed")


def purchase_order_update_events(
    purchase_order, transaction=None, transactions=None, audits=None
):
    audits = list(audits or [])
    payments = list(transactions or [])
    if transaction is not None and transaction not in payments:
        payments.append(transaction)
    actions = {audit.action for audit in audits}
    events = []
    if "purchase_order_placed" not in actions:
        events.append(
            {
                "timestamp": purchase_order.created_at,
                "label": "Purchase order placed",
                "summary": f"{purchase_order.vendor.name} purchase order was created.",
                "badge_class": "badge-brown",
                "actor": purchase_order.creator.name if purchase_order.creator else None,
                "purchase_order": purchase_order,
            }
        )
    for audit in audits:
        events.append(
            {
                "timestamp": audit.created_at,
                "label": PURCHASE_ORDER_UPDATE_LABELS.get(
                    audit.action, audit.action.replace("_", " ").title()
                ),
                "summary": audit.change_summary or "Purchase order updated.",
                "badge_class": purchase_order_update_badge(audit.action),
                "actor": audit.actor.name if audit.actor else None,
                "purchase_order": purchase_order,
            }
        )
    if (
        purchase_order.received_at
        and "purchase_order_received" not in actions
    ):
        events.append(
            {
                "timestamp": purchase_order.received_at,
                "label": "Received",
                "summary": "Raw material stock and finance were updated.",
                "badge_class": "badge-green",
                "actor": None,
                "purchase_order": purchase_order,
            }
        )
    for payment in payments:
        events.append(
            {
                "timestamp": payment.created_at,
                "label": "Payment recorded",
                "summary": (
                    f"Vendor payment of ₹{payment.amount or 0} recorded"
                    f"{' via ' + vendor_payment_method_label(payment.payment_method) if payment.payment_method else ''}."
                ),
                "badge_class": "badge-green",
                "actor": payment.creator.name if payment.creator else None,
                "purchase_order": purchase_order,
            }
        )
    return sorted(
        events,
        key=lambda event: event["timestamp"] or datetime.min,
        reverse=True,
    )


@admin_bp.route("/vendors")
@admin_required
@operations_required
def vendors():
    search = (request.args.get("q") or "").strip()
    query = Vendor.query
    if search:
        query = query.filter(
            or_(
                Vendor.name.ilike(f"%{search}%"),
                Vendor.contact_person.ilike(f"%{search}%"),
                Vendor.phone.ilike(f"%{search}%"),
                Vendor.email.ilike(f"%{search}%"),
                Vendor.gstin.ilike(f"%{search}%"),
                Vendor.pan.ilike(f"%{search}%"),
            )
        )
    vendors = query.order_by(Vendor.is_active.desc(), Vendor.name.asc()).all()
    show_add_vendor = request.args.get("add") == "1"
    return render_template(
        "admin/vendors.html",
        vendors=vendors,
        search=search,
        show_add_vendor=show_add_vendor,
        tds_payment_type_choices=TDS_PAYMENT_TYPE_CHOICES,
    )


@admin_bp.route("/vendors/add", methods=["POST"])
@admin_required
@manager_required
def add_vendor():
    name = (request.form.get("name") or "").strip()
    if not name:
        flash("Vendor name is required.", "danger")
        return redirect(url_for("admin.vendors"))
    if Vendor.query.filter(func.lower(Vendor.name) == name.lower()).first():
        flash("Vendor already exists.", "warning")
        return redirect(url_for("admin.vendors"))
    vendor = Vendor(
        name=name,
        contact_person=(request.form.get("contact_person") or "").strip() or None,
        phone=(request.form.get("phone") or "").strip() or None,
        email=(request.form.get("email") or "").strip() or None,
        address=(request.form.get("address") or "").strip() or None,
        payment_terms=(request.form.get("payment_terms") or "").strip() or None,
        gstin=(request.form.get("gstin") or "").strip().upper() or None,
        is_active=True,
    )
    try:
        apply_vendor_tds_form(vendor)
    except ValueError as exc:
        flash(str(exc), "danger")
        return redirect(url_for("admin.vendors", add=1))
    db.session.add(vendor)
    db.session.commit()
    flash("Vendor added successfully.", "success")
    return redirect(url_for("admin.vendor_detail", vendor_id=vendor.id))


@admin_bp.route("/vendors/<int:vendor_id>")
@admin_required
@operations_required
def vendor_detail(vendor_id):
    vendor = db.get_or_404(Vendor, vendor_id)
    purchase_orders = (
        PurchaseOrder.query.filter_by(vendor_id=vendor.id)
        .order_by(PurchaseOrder.order_date.desc(), PurchaseOrder.id.desc())
        .all()
    )
    spend_rows = get_container().finance_service.vendor_spend_report(
        start_date=date(2000, 1, 1),
        end_date=utcnow().date(),
    )
    spend = next((row for row in spend_rows if row["vendor_id"] == vendor.id), None)
    typical_costs = (
        VendorProduct.query.filter_by(vendor_id=vendor.id)
        .join(RawMaterial)
        .order_by(RawMaterial.name.asc())
        .all()
    )
    payment_history = vendor_payment_history(vendor, purchase_orders)
    return render_template(
        "admin/vendor_detail.html",
        vendor=vendor,
        purchase_orders=purchase_orders,
        spend=spend,
        typical_costs=typical_costs,
        payment_history=payment_history,
        payment_method_choices=VENDOR_PAYMENT_METHOD_CHOICES,
        tds_payment_type_choices=TDS_PAYMENT_TYPE_CHOICES,
    )


@admin_bp.route("/vendors/<int:vendor_id>/edit", methods=["POST"])
@admin_required
@manager_required
def edit_vendor(vendor_id):
    vendor = db.get_or_404(Vendor, vendor_id)
    name = (request.form.get("name") or "").strip()
    if not name:
        flash("Vendor name is required.", "danger")
        return redirect(url_for("admin.vendor_detail", vendor_id=vendor.id))
    duplicate = Vendor.query.filter(
        func.lower(Vendor.name) == name.lower(),
        Vendor.id != vendor.id,
    ).first()
    if duplicate:
        flash("Another vendor already uses that name.", "warning")
        return redirect(url_for("admin.vendor_detail", vendor_id=vendor.id))
    vendor.name = name
    vendor.contact_person = (request.form.get("contact_person") or "").strip() or None
    vendor.phone = (request.form.get("phone") or "").strip() or None
    vendor.email = (request.form.get("email") or "").strip() or None
    vendor.address = (request.form.get("address") or "").strip() or None
    vendor.payment_terms = (request.form.get("payment_terms") or "").strip() or None
    vendor.gstin = (request.form.get("gstin") or "").strip().upper() or None
    try:
        apply_vendor_tds_form(vendor)
    except ValueError as exc:
        flash(str(exc), "danger")
        return redirect(url_for("admin.vendor_detail", vendor_id=vendor.id))
    vendor.is_active = bool(request.form.get("is_active"))
    db.session.commit()
    flash("Vendor updated.", "success")
    return redirect(url_for("admin.vendor_detail", vendor_id=vendor.id))


@admin_bp.route("/purchase-orders")
@admin_required
@operations_required
def purchase_orders():
    status = (request.args.get("status") or "").strip().lower()
    query = PurchaseOrder.query.join(Vendor)
    if status:
        query = query.filter(PurchaseOrder.status == status)
    orders = query.order_by(
        PurchaseOrder.order_date.desc(), PurchaseOrder.id.desc()
    ).all()
    return render_template(
        "admin/purchase_orders.html", purchase_orders=orders, status=status
    )


@admin_bp.route("/purchase-orders/updates")
@admin_required
@operations_required
def purchase_order_updates():
    status = (request.args.get("status") or "").strip().lower()
    query = PurchaseOrder.query.options(
        selectinload(PurchaseOrder.vendor),
        selectinload(PurchaseOrder.creator),
    )
    if status:
        query = query.filter(PurchaseOrder.status == status)
    purchase_orders = (
        query.order_by(PurchaseOrder.created_at.desc(), PurchaseOrder.id.desc())
        .limit(100)
        .all()
    )
    purchase_order_ids = [po.id for po in purchase_orders]
    audits_by_order = purchase_order_audits(purchase_order_ids)
    transactions_by_order = purchase_order_transaction_map(purchase_order_ids)
    update_feed = []
    for purchase_order in purchase_orders:
        update_feed.extend(
            purchase_order_update_events(
                purchase_order,
                transactions=transactions_by_order.get(purchase_order.id),
                audits=audits_by_order.get(purchase_order.id),
            )
        )
    update_feed = sorted(
        update_feed,
        key=lambda event: event["timestamp"] or datetime.min,
        reverse=True,
    )[:100]
    return render_template(
        "admin/purchase_order_updates.html",
        purchase_orders=purchase_orders,
        update_feed=update_feed,
        status=status,
    )


@admin_bp.route("/purchase-orders/new", methods=["GET", "POST"])
@admin_required
@manager_required
def new_purchase_order():
    vendors = Vendor.query.filter_by(is_active=True).order_by(Vendor.name.asc()).all()
    materials = (
        RawMaterial.query.filter_by(is_active=True)
        .order_by(RawMaterial.name.asc())
        .all()
    )
    if request.method == "POST":
        vendor_id = request.form.get("vendor_id", type=int)
        vendor = db.session.get(Vendor, vendor_id)
        if vendor is None or not vendor.is_active:
            flash("Choose an active vendor.", "danger")
            return redirect(url_for("admin.new_purchase_order"))
        order_date_raw = request.form.get("order_date") or utcnow().date().isoformat()
        expected_raw = (request.form.get("expected_delivery_date") or "").strip()
        try:
            gst_rate = parse_decimal(
                request.form.get("gst_rate_percent") or "0", "GST rate"
            )
            order = PurchaseOrder(
                vendor_id=vendor.id,
                status="draft",
                order_date=date.fromisoformat(order_date_raw),
                expected_delivery_date=(
                    date.fromisoformat(expected_raw) if expected_raw else None
                ),
                notes=(request.form.get("notes") or "").strip() or None,
                created_by=current_user.id,
                gst_rate_percent=gst_rate,
            )
            db.session.add(order)
            db.session.flush()
            material_ids = request.form.getlist("raw_material_id[]")
            quantities = request.form.getlist("quantity[]")
            unit_costs = request.form.getlist("unit_cost[]")
            item_count = 0
            blank_line_seen = False
            for line_number, (raw_id, qty_raw, cost_raw) in enumerate(
                zip(material_ids, quantities, unit_costs),
                start=1,
            ):
                raw_id = (raw_id or "").strip()
                qty_raw = (qty_raw or "").strip()
                cost_raw = (cost_raw or "").strip()
                line_has_any_value = bool(raw_id or qty_raw or cost_raw)
                if not line_has_any_value:
                    blank_line_seen = True
                    continue
                if blank_line_seen:
                    raise ValueError(
                        "Complete each material line before adding another material."
                    )
                if not raw_id or not qty_raw or not cost_raw:
                    raise ValueError(
                        f"Complete material, quantity, and unit cost for line {line_number}."
                    )
                material = db.session.get(RawMaterial, int(raw_id))
                if material is None or not material.is_active:
                    raise ValueError(f"Choose an active material for line {line_number}.")
                quantity = parse_decimal(qty_raw, f"{material.name} quantity")
                unit_cost = parse_decimal(cost_raw, f"{material.name} unit cost")
                if quantity <= 0:
                    raise ValueError(f"{material.name} quantity must be greater than zero.")
                if unit_cost < 0:
                    raise ValueError(f"{material.name} unit cost cannot be negative.")
                db.session.add(
                    PurchaseOrderItem(
                        purchase_order_id=order.id,
                        raw_material_id=material.id,
                        quantity=quantity,
                        unit_cost=unit_cost,
                    )
                )
                item_count += 1
            if item_count == 0:
                db.session.rollback()
                flash("Add at least one raw material line.", "danger")
                return redirect(url_for("admin.new_purchase_order"))
            log_purchase_order_update(
                order,
                "purchase_order_placed",
                current_user.id,
                f"Purchase order #{order.id} placed for {vendor.name}.",
                after={
                    "vendor_id": vendor.id,
                    "status": order.status,
                    "item_count": item_count,
                    "expected_delivery_date": order.expected_delivery_date,
                },
            )
        except (ValueError, TypeError) as exc:
            db.session.rollback()
            flash(str(exc), "danger")
            return redirect(url_for("admin.new_purchase_order"))
        db.session.commit()
        flash("Purchase order created.", "success")
        return redirect(url_for("admin.purchase_order_detail", order_id=order.id))
    return render_template(
        "admin/purchase_order_form.html",
        vendors=vendors,
        materials=materials,
        today=utcnow().date().isoformat(),
        selected_vendor_id=request.args.get("vendor_id", type=int),
    )


@admin_bp.route("/purchase-orders/<int:order_id>")
@admin_required
@operations_required
def purchase_order_detail(order_id):
    purchase_order = db.get_or_404(PurchaseOrder, order_id)
    po_service = get_container().purchase_order_service
    payments = po_service.payments(purchase_order)
    transaction = payments[-1] if payments else None
    paid_amount = po_service.paid_amount(purchase_order)
    remaining_amount = po_service.remaining_amount(purchase_order)
    audits = purchase_order_audits([purchase_order.id]).get(purchase_order.id, [])
    update_events = purchase_order_update_events(
        purchase_order,
        transaction=transaction,
        transactions=payments,
        audits=audits,
    )
    tds_preview = get_container().finance_service.purchase_order_tds_preview(
        purchase_order
    )
    return render_template(
        "admin/purchase_order_detail.html",
        purchase_order=purchase_order,
        transaction=transaction,
        payments=payments,
        paid_amount=paid_amount,
        remaining_amount=remaining_amount,
        payment_method_choices=VENDOR_PAYMENT_METHOD_CHOICES,
        payment_method_label=vendor_payment_method_label,
        mask_reference=mask_payment_reference,
        update_events=update_events,
        tds_preview=tds_preview,
    )


@admin_bp.route("/purchase-orders/<int:order_id>/status", methods=["POST"])
@admin_required
@manager_required
def update_purchase_order_status(order_id):
    purchase_order = db.get_or_404(PurchaseOrder, order_id)
    action = (request.form.get("action") or "").strip().lower()
    if action not in {"ordered", "received", "cancelled"}:
        flash("Choose a valid purchase order action.", "danger")
        return redirect(
            url_for("admin.purchase_order_detail", order_id=purchase_order.id)
        )
    try:
        if action == "received":
            batch_details = {}
            for item in purchase_order.items.all():
                prefix = f"batch_{item.id}_"
                row = {
                    key.replace(prefix, ""): (value or "").strip()
                    for key, value in request.form.items()
                    if key.startswith(prefix)
                }
                if row:
                    batch_details[item.id] = row
            payment_amount = request.form.get("payment_amount")
            try:
                payment_amount = (
                    Decimal(str(payment_amount)) if payment_amount not in (None, "") else None
                )
            except Exception:
                payment_amount = None
            get_container().purchase_order_service.receive_purchase_order(
                purchase_order,
                actor_id=current_user.id,
                payment_method=normalize_vendor_payment_method(
                    request.form.get("payment_method")
                ),
                payment_amount=payment_amount,
                batch_details=batch_details,
            )
        else:
            if purchase_order.status == "received":
                flash("Received purchase orders cannot be changed.", "warning")
                return redirect(
                    url_for("admin.purchase_order_detail", order_id=purchase_order.id)
                )
            previous_status = purchase_order.status
            purchase_order.status = action
            if previous_status != action:
                log_purchase_order_update(
                    purchase_order,
                    f"purchase_order_{action}",
                    current_user.id,
                    f"Purchase order #{purchase_order.id} marked {action}.",
                    before={"status": previous_status},
                    after={"status": action},
                )
        db.session.commit()
    except ValidationError as exc:
        db.session.rollback()
        flash(str(exc), "danger")
        return redirect(
            url_for("admin.purchase_order_detail", order_id=purchase_order.id)
        )
    flash(f"Purchase order marked {action}.", "success")
    return redirect(url_for("admin.purchase_order_detail", order_id=purchase_order.id))


@admin_bp.route("/purchase-orders/<int:order_id>/payments", methods=["POST"])
@admin_required
@manager_required
def record_purchase_payment(order_id):
    purchase_order = db.get_or_404(PurchaseOrder, order_id)
    payment_method = normalize_vendor_payment_method(request.form.get("payment_method"))
    payment_amount = request.form.get("payment_amount")
    try:
        payment_amount = (
            Decimal(str(payment_amount)) if payment_amount not in (None, "") else None
        )
    except Exception:
        payment_amount = None
    try:
        get_container().purchase_order_service.record_purchase_payment(
            purchase_order,
            amount=payment_amount,
            payment_method=payment_method,
            references=request.form.get("references", ""),
            notes=request.form.get("notes", ""),
            actor_id=current_user.id,
        )
        db.session.commit()
    except ValidationError as exc:
        db.session.rollback()
        flash(str(exc), "danger")
        return redirect(
            url_for("admin.purchase_order_detail", order_id=purchase_order.id)
        )
    flash("Payment recorded.", "success")
    return redirect(url_for("admin.purchase_order_detail", order_id=purchase_order.id))


@admin_bp.route("/delivery-settings", methods=["GET", "POST"])
@admin_required
@manager_required
def delivery_settings():
    service = get_container().delivery_zone_service
    if request.method == "POST":
        branch_id = request.form.get("branch_id", type=int)
        if branch_id:
            scoped_branch_or_404(branch_id)
        before = {}
        setting = service.ensure_default_rules(branch_id)
        before = {
            "max_radius_km": float(setting.max_radius_km or 0),
            "free_radius_km": float(setting.free_radius_km or 0),
            "min_order_value": float(setting.min_order_value or 0),
            "extra_fee": float(setting.extra_fee or 0),
            "is_delivery_enabled": bool(setting.is_delivery_enabled),
            "is_pickup_enabled": bool(setting.is_pickup_enabled),
        }
        setting.max_radius_km = Decimal(str(request.form.get("max_radius_km") or 7))
        setting.free_radius_km = Decimal(str(request.form.get("free_radius_km") or 3))
        setting.min_order_value = Decimal(str(request.form.get("min_order_value") or 0))
        setting.extra_fee = Decimal(str(request.form.get("extra_fee") or 0))
        setting.is_delivery_enabled = bool(request.form.get("is_delivery_enabled"))
        setting.is_pickup_enabled = bool(request.form.get("is_pickup_enabled"))

        paid_fee = Decimal(str(request.form.get("paid_band_fee") or 50))
        free_radius = Decimal(str(setting.free_radius_km or 3))
        max_radius = Decimal(str(setting.max_radius_km or 7))
        DeliveryDistanceBand.query.filter_by(branch_id=branch_id).delete()
        db.session.add_all(
            [
                DeliveryDistanceBand(
                    branch_id=branch_id,
                    min_distance_km=Decimal("0.00"),
                    max_distance_km=free_radius,
                    delivery_fee=Decimal("0.00"),
                ),
                DeliveryDistanceBand(
                    branch_id=branch_id,
                    min_distance_km=free_radius,
                    max_distance_km=max_radius,
                    delivery_fee=paid_fee,
                ),
            ]
        )
        get_container().audit_service.log(
            current_user,
            "delivery_rule_changed",
            "DeliveryZoneSetting",
            setting.id,
            before=before,
            after={
                "max_radius_km": float(setting.max_radius_km or 0),
                "free_radius_km": float(setting.free_radius_km or 0),
                "min_order_value": float(setting.min_order_value or 0),
                "extra_fee": float(setting.extra_fee or 0),
                "paid_band_fee": float(paid_fee or 0),
            },
            branch_id=branch_id,
            change_summary="Delivery zone settings updated.",
        )
        db.session.commit()
        flash("Delivery settings saved.", "success")
        return redirect(url_for("admin.delivery_settings"))

    branch_id = request.args.get("branch_id", type=int)
    branches = scoped_branch_query(Branch.query).order_by(Branch.name.asc()).all()
    if not branch_id and branches:
        branch_id = branches[0].id
    if branch_id:
        scoped_branch_or_404(branch_id)
    setting = service.ensure_default_rules(branch_id)
    db.session.commit()
    bands = (
        DeliveryDistanceBand.query.filter_by(branch_id=branch_id)
        .order_by(DeliveryDistanceBand.min_distance_km.asc())
        .all()
    )
    pincode_rules = (
        DeliveryPincodeRule.query.filter(
            or_(DeliveryPincodeRule.branch_id == branch_id, DeliveryPincodeRule.branch_id.is_(None))
        )
        .order_by(DeliveryPincodeRule.pincode.asc())
        .all()
    )
    return render_template(
        "admin/delivery_settings.html",
        branches=branches,
        selected_branch_id=branch_id,
        setting=setting,
        bands=bands,
        pincode_rules=pincode_rules,
    )


@admin_bp.route("/delivery-settings/pincode", methods=["POST"])
@admin_required
@manager_required
def add_delivery_pincode_rule():
    branch_id = request.form.get("branch_id", type=int)
    if branch_id:
        scoped_branch_or_404(branch_id)
    pincode = re.sub(r"\D+", "", request.form.get("pincode") or "")
    if len(pincode) != 6:
        flash("Enter a valid 6-digit pincode.", "danger")
        return redirect(url_for("admin.delivery_settings", branch_id=branch_id))
    status = (request.form.get("status") or "supported").strip().lower()
    if status not in {"supported", "partial", "blocked"}:
        status = "supported"
    rule = DeliveryPincodeRule.query.filter_by(
        branch_id=branch_id,
        pincode=pincode,
    ).first()
    before = None
    if rule is None:
        rule = DeliveryPincodeRule(branch_id=branch_id, pincode=pincode)
        db.session.add(rule)
    else:
        before = {"status": rule.status, "delivery_fee_override": float(rule.delivery_fee_override or 0)}
    rule.status = status
    rule.delivery_fee_override = (
        Decimal(str(request.form.get("delivery_fee_override")))
        if (request.form.get("delivery_fee_override") or "").strip()
        else None
    )
    rule.estimated_delivery_minutes = request.form.get("estimated_delivery_minutes", type=int)
    rule.notes = (request.form.get("notes") or "").strip() or None
    rule.is_active = True
    db.session.flush()
    get_container().audit_service.log(
        current_user,
        "delivery_pincode_rule_changed",
        "DeliveryPincodeRule",
        rule.id,
        before=before,
        after={"pincode": pincode, "status": status},
        branch_id=branch_id,
        change_summary=f"Delivery pincode rule saved for {pincode}.",
    )
    db.session.commit()
    flash("Pincode rule saved.", "success")
    return redirect(url_for("admin.delivery_settings", branch_id=branch_id))


@admin_bp.route("/branches")
@admin_required
@manager_required
def branches():
    branches = scoped_branch_query(Branch.query).order_by(
        Branch.is_active.desc(), Branch.name
    ).all()
    for branch in branches:
        branch.detail_summary = _branch_detail_summary(branch)
    return render_template(
        "admin/branches.html",
        branches=branches,
        branch_employee_role_choices=branch_employee_role_choices_for_current_user(),
        branch_employee_role_labels=BRANCH_EMPLOYEE_ROLE_LABELS,
        staff_access_choices=STAFF_PORTAL_ACCESS_CHOICES,
        can_assign_branch_managers=has_global_admin_data_access(),
    )


@admin_bp.route("/branches/add", methods=["POST"])
@admin_required
@owner_required
def add_branch():
    name = (request.form.get("name") or "").strip()
    if not name:
        flash("Branch name is required.", "danger")
        return redirect(url_for("admin.branches"))
    if Branch.query.filter(func.lower(Branch.name) == name.lower()).first():
        flash("Branch already exists.", "warning")
        return redirect(url_for("admin.branches"))
    branch = Branch(
        name=name,
        manager_name=(request.form.get("manager_name") or "").strip(),
        phone=(request.form.get("phone") or "").strip(),
        address=(request.form.get("address") or "").strip(),
    )
    db.session.add(branch)
    db.session.commit()
    flash("Branch added successfully.", "success")
    return redirect(url_for("admin.branches"))


@admin_bp.route("/branches/<int:branch_id>/toggle", methods=["POST"])
@admin_required
@manager_required
def toggle_branch_status(branch_id):
    branch = scoped_branch_or_404(branch_id)
    branch.is_active = not branch.is_active
    db.session.commit()
    flash(
        f"Branch {'opened' if branch.is_active else 'closed'}.",
        "success" if branch.is_active else "warning",
    )
    return redirect(url_for("admin.branches"))


@admin_bp.route("/branches/<int:branch_id>/employees/add", methods=["POST"])
@admin_required
@manager_required
def add_branch_employee(branch_id):
    branch = scoped_branch_or_404(branch_id)
    name = (request.form.get("name") or "").strip()
    email = (request.form.get("email") or "").strip().lower()
    phone = (request.form.get("phone") or "").strip()
    role = validate_branch_employee_role(request.form.get("role"))
    password = (request.form.get("password") or "").strip()

    if not name or not email or not role or not password:
        flash("Employee name, email, role, and temporary password are required.", "danger")
        return branch_employee_redirect(branch.id)
    if User.query.filter(func.lower(User.email) == email.lower()).first():
        flash("A user with that email already exists.", "warning")
        return branch_employee_redirect(branch.id)
    password_errors = validate_password(password)
    if password_errors:
        for error in password_errors:
            flash(error, "danger")
        return branch_employee_redirect(branch.id)

    employee = User(
        name=name,
        email=email,
        phone=phone,
        role=role,
        admin_tier=branch_employee_admin_tier(role),
        branch_id=branch.id,
        is_active=True,
        email_locked=True,
    )
    try:
        apply_staff_profile_from_form(employee, role)
    except ValidationError as exc:
        flash(str(exc), "danger")
        return branch_employee_redirect(branch.id)
    employee.set_password(password, require_change=True)
    db.session.add(employee)
    db.session.flush()
    get_container().audit_service.log(
        current_user,
        "branch_employee_created",
        "User",
        employee.id,
        after={
            "email": employee.email,
            "role": employee.role,
            "branch_id": employee.branch_id,
            "is_active": employee.is_active,
            "date_of_joining": (
                employee.date_of_joining.isoformat()
                if employee.date_of_joining
                else None
            ),
            "designation": employee.designation,
            "email_locked": employee.email_locked,
            "portal_access": staff_portal_access_values(employee),
        },
        branch_id=branch.id,
        change_summary=f"Branch employee created for {branch.name}: {employee.email}.",
    )
    db.session.commit()
    flash(f"{employee.name} added to {branch.name}.", "success")
    return branch_employee_redirect(branch.id)


@admin_bp.route(
    "/branches/<int:branch_id>/employees/<int:user_id>/edit", methods=["POST"]
)
@admin_required
@manager_required
def edit_branch_employee(branch_id, user_id):
    branch, employee = branch_employee_or_404(branch_id, user_id)
    name = (request.form.get("name") or "").strip()
    email = (request.form.get("email") or "").strip().lower()
    phone = (request.form.get("phone") or "").strip()
    role = validate_branch_employee_role(request.form.get("role"))
    access_status = (request.form.get("access_status") or "active").strip().lower()
    password = (request.form.get("password") or "").strip()

    if not name or not role:
        flash("Employee name and role are required.", "danger")
        return branch_employee_redirect(branch.id)
    if email and email != (employee.email or "").lower():
        flash("Staff email is locked and cannot be changed after creation.", "info")
    if access_status not in {"active", "inactive"}:
        flash("Choose a valid access status.", "danger")
        return branch_employee_redirect(branch.id)
    if employee.id == current_user.id and access_status == "inactive":
        flash("You cannot deactivate your own account from the branch page.", "warning")
        return branch_employee_redirect(branch.id)
    if password:
        password_errors = validate_password(password)
        if password_errors:
            for error in password_errors:
                flash(error, "danger")
            return branch_employee_redirect(branch.id)

    before = {
        "name": employee.name,
        "email": employee.email,
        "phone": employee.phone,
        "role": employee.role,
        "admin_tier": employee.admin_tier,
        "is_active": employee.is_active,
        "staff_address": employee.staff_address,
        "date_of_joining": (
            employee.date_of_joining.isoformat()
            if employee.date_of_joining
            else None
        ),
        "designation": employee.designation,
        "emergency_contact": employee.emergency_contact,
        "staff_notes": employee.staff_notes,
        "portal_access": staff_portal_access_values(employee),
    }
    employee.name = name
    employee.phone = phone
    employee.role = role
    employee.admin_tier = branch_employee_admin_tier(role)
    employee.branch_id = branch.id
    employee.is_active = access_status == "active"
    employee.email_locked = True
    try:
        apply_staff_profile_from_form(employee, role)
    except ValidationError as exc:
        flash(str(exc), "danger")
        return branch_employee_redirect(branch.id)
    if password:
        employee.set_password(password, require_change=True)

    get_container().audit_service.log(
        current_user,
        "branch_employee_updated",
        "User",
        employee.id,
        before=before,
        after={
            "name": employee.name,
            "email": employee.email,
            "phone": employee.phone,
            "role": employee.role,
            "admin_tier": employee.admin_tier,
            "is_active": employee.is_active,
            "staff_address": employee.staff_address,
            "date_of_joining": (
                employee.date_of_joining.isoformat()
                if employee.date_of_joining
                else None
            ),
            "designation": employee.designation,
            "emergency_contact": employee.emergency_contact,
            "staff_notes": employee.staff_notes,
            "email_locked": employee.email_locked,
            "portal_access": staff_portal_access_values(employee),
            "password_changed": bool(password),
        },
        branch_id=branch.id,
        change_summary=f"Branch employee updated for {branch.name}: {employee.email}.",
    )
    db.session.commit()
    flash(f"{employee.name}'s branch details were updated.", "success")
    return branch_employee_redirect(branch.id)


@admin_bp.route("/production")
@admin_required
@manager_required
def production():
    plans = scope_query_to_admin_branch(
        ProductionPlan.query,
        ProductionPlan.branch_id,
        include_unassigned=has_global_admin_data_access(),
    ).order_by(ProductionPlan.planned_date.desc()).all()
    batches = (
        scope_query_to_admin_branch(
            ProductionBatch.query,
            ProductionBatch.branch_id,
            include_unassigned=has_global_admin_data_access(),
        )
        .order_by(ProductionBatch.produced_at.desc())
        .limit(25)
        .all()
    )
    products = Product.query.order_by(Product.name).all()
    branches = scoped_branch_query(Branch.query).order_by(Branch.name).all()
    return render_template(
        "admin/production.html",
        plans=plans,
        batches=batches,
        products=products,
        branches=branches,
    )


@admin_bp.route("/production/add", methods=["POST"])
@admin_required
@manager_required
def add_production_plan():
    product_id = request.form.get("product_id", type=int)
    planned_date = request.form.get("planned_date")
    quantity = request.form.get("quantity", type=int)
    branch_id = request.form.get("branch_id", type=int)
    if not has_global_admin_data_access():
        branch_id = current_admin_branch_id()
    if branch_id:
        scoped_branch_or_404(branch_id)
    if not product_id or not planned_date or quantity is None:
        flash("Product, date, and quantity are required.", "danger")
        return redirect(url_for("admin.production"))
    try:
        planned_date = datetime.strptime(planned_date, "%Y-%m-%d")
    except ValueError:
        flash("Invalid production date.", "danger")
        return redirect(url_for("admin.production"))
    plan = ProductionPlan(
        product_id=product_id,
        branch_id=branch_id if branch_id else None,
        planned_date=planned_date,
        quantity=quantity,
        status=request.form.get("status", "Scheduled"),
        notes=(request.form.get("notes") or "").strip(),
    )
    db.session.add(plan)
    db.session.commit()
    flash("Production plan created.", "success")
    return redirect(url_for("admin.production"))


@admin_bp.route("/batches")
@admin_required
@manager_required
def batches():
    batches = scope_query_to_admin_branch(
        ProductionBatch.query,
        ProductionBatch.branch_id,
        include_unassigned=has_global_admin_data_access(),
    ).order_by(ProductionBatch.produced_at.desc()).all()
    products = Product.query.order_by(Product.name).all()
    branches = scoped_branch_query(Branch.query).order_by(Branch.name).all()
    return render_template(
        "admin/batches.html", batches=batches, products=products, branches=branches
    )


@admin_bp.route("/batches/add", methods=["POST"])
@admin_required
@manager_required
def add_batch():
    product_id = request.form.get("product_id", type=int)
    branch_id = request.form.get("branch_id", type=int)
    if not has_global_admin_data_access():
        branch_id = current_admin_branch_id()
    if branch_id:
        scoped_branch_or_404(branch_id)
    produced_at = request.form.get("produced_at")
    expiry_date = request.form.get("expiry_date")
    quantity = request.form.get("quantity", type=int)
    waste_percentage = request.form.get("waste_percentage", type=float) or 0
    if not product_id or not produced_at or quantity is None:
        flash("Product, production date, and quantity are required.", "danger")
        return redirect(url_for("admin.batches"))
    try:
        produced_at = datetime.strptime(produced_at, "%Y-%m-%d")
    except ValueError:
        flash("Invalid production date.", "danger")
        return redirect(url_for("admin.batches"))
    expiry_dt = None
    if expiry_date:
        try:
            expiry_dt = datetime.strptime(expiry_date, "%Y-%m-%d")
        except ValueError:
            flash("Invalid expiry date.", "danger")
            return redirect(url_for("admin.batches"))
    batch = ProductionBatch(
        product_id=product_id,
        branch_id=branch_id if branch_id else None,
        produced_at=produced_at,
        expiry_date=expiry_dt,
        quantity=quantity,
        waste_percentage=waste_percentage,
        status=request.form.get("status", "Produced"),
        notes=(request.form.get("notes") or "").strip(),
    )
    db.session.add(batch)
    db.session.commit()
    flash("Production batch logged.", "success")
    return redirect(url_for("admin.batches"))


@admin_bp.route("/batches/<int:batch_id>/update", methods=["POST"])
@admin_required
@manager_required
def update_batch(batch_id):
    batch = db.get_or_404(ProductionBatch, batch_id)
    abort_if_no_branch_access(batch.branch_id)
    batch.status = request.form.get("status", batch.status)
    batch.notes = (request.form.get("notes") or "").strip()
    try:
        batch.waste_percentage = float(
            request.form.get("waste_percentage", batch.waste_percentage) or 0
        )
    except ValueError:
        flash("Invalid waste percentage.", "danger")
        return redirect(url_for("admin.batches"))
    db.session.commit()
    flash("Batch updated.", "success")
    return redirect(url_for("admin.batches"))


RAW_MATERIAL_STOCK_STATUS_VALUES = {
    "in_stock",
    "low_stock",
    "out_of_stock",
    "reorder_required",
    "expiring_soon",
    "expired",
}
RAW_MATERIAL_EXPIRY_VALUES = {"none", "ok", "expiring_soon", "expired"}


def _material_expiry_status(material, expiry_filter):
    status = material.expiry_summary["status"]
    if expiry_filter == "none":
        return status == "none"
    if expiry_filter == "ok":
        return status == "ok"
    if expiry_filter == "expiring_soon":
        return status == "expiring_soon"
    if expiry_filter == "expired":
        return status == "expired"
    return True


@admin_bp.route("/raw-materials")
@admin_required
@operations_required
def raw_materials():
    search = (request.args.get("q") or "").strip()
    selected_material_id = request.args.get("material_id", type=int)
    show_add_material = request.args.get("add") == "1"
    page = request.args.get("page", 1, type=int) or 1
    per_page = request.args.get("per_page", 12, type=int) or 12
    per_page = max(1, min(per_page, 50))
    sort_by = (request.args.get("sort") or "name").strip().lower()
    if sort_by not in {"name", "stock", "last_purchase", "expiry", "value"}:
        sort_by = "name"
    category = (request.args.get("category") or "").strip() or None
    stock_status = (request.args.get("status") or "").strip().lower() or None
    if stock_status not in RAW_MATERIAL_STOCK_STATUS_VALUES:
        stock_status = None
    expiry_filter = (request.args.get("expiry") or "").strip().lower() or None
    if expiry_filter not in RAW_MATERIAL_EXPIRY_VALUES:
        expiry_filter = None
    supplier_id = request.args.get("supplier_id", type=int) or None
    location = (request.args.get("location") or "").strip() or None
    last_purchase_days = request.args.get("last_purchase", type=int) or None

    query = scoped_material_query(RawMaterial.query)
    if selected_material_id:
        query = query.filter(RawMaterial.id == selected_material_id)
    if search:
        like = f"%{search}%"
        query = query.outerjoin(Vendor, Vendor.id == RawMaterial.preferred_supplier_id)
        query = query.filter(
            or_(
                RawMaterial.name.ilike(like),
                RawMaterial.sku.ilike(like),
                RawMaterial.unit.ilike(like),
                RawMaterial.supplier.ilike(like),
                RawMaterial.notes.ilike(like),
                RawMaterial.category.ilike(like),
                RawMaterial.storage_location.ilike(like),
                Vendor.name.ilike(like),
                RawMaterial.batches.any(MaterialBatch.batch_number.ilike(like)),
            )
        )
    if category:
        query = query.filter(RawMaterial.category == category)
    if location:
        query = query.filter(RawMaterial.storage_location == location)
    if supplier_id:
        query = query.filter(RawMaterial.preferred_supplier_id == supplier_id)
    if last_purchase_days:
        cutoff = date.today() - timedelta(days=last_purchase_days)
        query = query.filter(
            RawMaterial.last_purchased_at >= datetime.combine(cutoff, time.min)
        )

    materials = query.all()
    if stock_status == "expiring_soon" or stock_status == "expired":
        filtered = [
            material
            for material in materials
            if material.expiry_summary["status"] == stock_status
        ]
        materials = filtered
    elif stock_status:
        filtered = []
        for material in materials:
            if stock_status == "in_stock" and material.stock_status == "in_stock":
                filtered.append(material)
            elif stock_status == "low_stock" and material.stock_status == "low_stock":
                filtered.append(material)
            elif stock_status == "out_of_stock" and material.stock_status == "out_of_stock":
                filtered.append(material)
            elif stock_status == "reorder_required" and material.reorder_required:
                filtered.append(material)
        materials = filtered
    if expiry_filter and stock_status not in {"expiring_soon", "expired"}:
        materials = [
            material
            for material in materials
            if _material_expiry_status(material, expiry_filter)
        ]

    def _sort_key(material):
        if sort_by == "stock":
            return (not material.is_active, Decimal("0") - Decimal(material.stock or 0), material.name.lower())
        if sort_by == "last_purchase":
            return (
                not material.is_active,
                material.last_purchased_at is None,
                material.last_purchased_at or datetime.min,
                material.name.lower(),
            )
        if sort_by == "expiry":
            nearest = material.expiry_summary["nearest"]
            return (not material.is_active, nearest is None, nearest or date.max, material.name.lower())
        if sort_by == "value":
            return (not material.is_active, Decimal("0") - material.inventory_value, material.name.lower())
        return (not material.is_active, material.name.lower())

    materials.sort(key=_sort_key)

    total_count = len(materials)
    start = (page - 1) * per_page
    end = start + per_page
    page_materials = materials[start:end]

    class _Pagination:
        pass

    pagination = _Pagination()
    pagination.page = page
    pagination.per_page = per_page
    pagination.total = total_count
    pagination.items = page_materials
    pagination.pages = max(1, -(-total_count // per_page)) if total_count else 1
    pagination.has_prev = page > 1
    pagination.has_next = page < pagination.pages
    pagination.prev_num = max(1, page - 1)
    pagination.next_num = min(pagination.pages, page + 1)
    pagination.iter_pages = lambda *a, **k: range(1, pagination.pages + 1)

    inventory_service = get_container().inventory_service
    summary = inventory_service.stock_summary(materials)

    def page_url(page_number, **overrides):
        args = request.args.to_dict(flat=True)
        args.pop("page", None)
        args.update(overrides)
        args["page"] = page_number
        return url_for("admin.raw_materials", **args)

    def filter_url(**overrides):
        args = request.args.to_dict(flat=True)
        args.pop("page", None)
        args.update(overrides)
        return url_for("admin.raw_materials", **args)

    summary_cards = [
        {
            "key": "total",
            "label": "Total Materials",
            "value": summary["total"],
            "tone": "default",
            "url": filter_url(),
        },
        {
            "key": "low",
            "label": "Low Stock",
            "value": summary["low"],
            "tone": "warning",
            "url": filter_url(status="low_stock"),
        },
        {
            "key": "out",
            "label": "Out of Stock",
            "value": summary["out"],
            "tone": "danger",
            "url": filter_url(status="out_of_stock"),
        },
        {
            "key": "expiring",
            "label": "Expiring Soon",
            "value": summary["expiring"],
            "tone": "info",
            "url": filter_url(status="expiring_soon"),
        },
        {
            "key": "value",
            "label": "Inventory Value",
            "value": summary["value"],
            "tone": "success",
            "value_format": "currency",
            "url": filter_url(),
        },
    ]

    category_options = [
        row[0]
        for row in scoped_material_query(
            RawMaterial.query.with_entities(RawMaterial.category).distinct()
        )
        .order_by(RawMaterial.category.asc())
        .all()
        if row[0]
    ]
    location_options = [
        row[0]
        for row in scoped_material_query(
            RawMaterial.query.with_entities(RawMaterial.storage_location).distinct()
        )
        .order_by(RawMaterial.storage_location.asc())
        .all()
        if row[0]
    ]
    supplier_options = Vendor.query.order_by(Vendor.name.asc()).all()

    return render_template(
        "admin/raw_materials.html",
        materials=page_materials,
        pagination=pagination,
        search=search,
        selected_material_id=selected_material_id,
        show_add_material=show_add_material,
        sort_by=sort_by,
        category=category,
        stock_status=stock_status,
        expiry_filter=expiry_filter,
        supplier_id=supplier_id,
        location=location,
        last_purchase_days=last_purchase_days,
        summary_cards=summary_cards,
        category_options=category_options,
        location_options=location_options,
        supplier_options=supplier_options,
        stock_status_options=[
            ("", "All statuses"),
            ("in_stock", "In Stock"),
            ("low_stock", "Low Stock"),
            ("out_of_stock", "Out of Stock"),
            ("reorder_required", "Reorder Required"),
            ("expiring_soon", "Expiring Soon"),
            ("expired", "Expired"),
        ],
        expiry_options=[
            ("", "Any expiry"),
            ("none", "No expiry tracked"),
            ("ok", "OK"),
            ("expiring_soon", "Expiring Soon"),
            ("expired", "Expired"),
        ],
        last_purchase_options=[
            ("", "Any purchase date"),
            ("30", "Last 30 days"),
            ("60", "Last 60 days"),
            ("90", "Last 90 days"),
            ("180", "Last 6 months"),
        ],
        page_url=page_url,
    )


@admin_bp.route("/raw-materials/<int:material_id>")
@admin_required
@operations_required
def material_detail(material_id):
    mat = scoped_material_or_404(material_id)
    inventory_service = get_container().inventory_service
    context = inventory_service.material_detail_context(mat)
    context["vendors"] = (
        Vendor.query.filter_by(is_active=True).order_by(Vendor.name.asc()).all()
    )
    context["document_type_options"] = [
        (value, MATERIAL_DOCUMENT_TYPE_LABELS.get(value, value))
        for value in MATERIAL_DOCUMENT_TYPE_VALUES
    ]
    context["document_type_labels"] = MATERIAL_DOCUMENT_TYPE_LABELS
    context["batch_status_options"] = [
        (value, BATCH_STATUS_LABELS.get(value, value))
        for value in (
            "available",
            "partially_used",
            "fully_used",
            "expired",
            "damaged",
            "returned",
            "blocked",
        )
    ]
    context["stock_reason_options"] = [
        (reason, STOCK_MOVEMENT_REASON_LABELS.get(reason, reason))
        for reason in (
            "manual_restock",
            "usage",
            "wastage",
            "damage",
            "expired",
            "return_to_supplier",
            "correction",
        )
    ]
    context["last_purchase"] = get_container().purchase_order_service.last_purchase_summary(
        mat
    )
    return render_template("admin/raw_material_detail.html", **context)


@admin_bp.route("/raw-materials/add", methods=["POST"])
@admin_required
@manager_required
def add_raw_material():
    name = request.form.get("name", "").strip()
    if not name:
        flash("Material name is required.", "danger")
        return redirect(url_for("admin.raw_materials", add=1))
    if RawMaterial.query.filter(func.lower(RawMaterial.name) == name.lower()).first():
        flash("A material with that name already exists.", "warning")
        return redirect(url_for("admin.raw_materials", add=1))
    try:
        opening_stock = parse_decimal(request.form.get("opening_stock"), "opening stock")
        reorder = parse_decimal(request.form.get("reorder_level"), "reorder level")
        cost = parse_decimal(request.form.get("cost_per_unit"), "cost per unit")
    except ValueError as e:
        flash(str(e), "danger")
        return redirect(url_for("admin.raw_materials", add=1))
    preferred_supplier_raw = (request.form.get("preferred_supplier_id") or "").strip()
    preferred_supplier_id = int(preferred_supplier_raw) if preferred_supplier_raw else None
    material = RawMaterial(
        name=name,
        sku=(request.form.get("sku") or "").strip() or None,
        category=(request.form.get("category") or "").strip() or None,
        branch_id=current_admin_branch_id(),
        unit=request.form.get("unit", "").strip() or "kg",
        stock=0,
        reorder_level=reorder,
        cost_per_unit=cost,
        min_stock=parse_decimal(request.form.get("min_stock"), "minimum stock")
        if request.form.get("min_stock", "").strip()
        else None,
        max_stock=parse_decimal(request.form.get("max_stock"), "maximum stock")
        if request.form.get("max_stock", "").strip()
        else None,
        supplier=request.form.get("supplier", "").strip() or None,
        preferred_supplier_id=preferred_supplier_id,
        storage_location=(request.form.get("storage_location") or "").strip() or None,
        shelf_life_days=int(request.form.get("shelf_life_days") or 0) or None,
        tax_rate_percent=parse_decimal(request.form.get("tax_rate_percent"), "tax rate")
        if request.form.get("tax_rate_percent", "").strip()
        else None,
        notes=request.form.get("notes", "").strip() or None,
        updated_by=current_user.id,
    )
    db.session.add(material)
    db.session.flush()
    inventory_service = get_container().inventory_service
    if opening_stock > 0:
        inventory_service.increase_raw_material_stock(
            material,
            opening_stock,
            reason="manual_restock",
            created_by=current_user.id,
        )
    db.session.commit()
    try:
        check_and_send_inventory_alerts()
    except Exception:
        pass
    flash("Raw material added.", "success")
    return redirect(url_for("admin.raw_materials"))


@admin_bp.route("/raw-materials/<int:material_id>/details", methods=["POST"])
@admin_required
@manager_required
def update_raw_material_details(material_id):
    mat = scoped_material_or_404(material_id)
    try:
        get_container().inventory_service.update_material_details(
            mat, request.form, actor_id=current_user.id
        )
        db.session.commit()
        try:
            check_and_send_inventory_alerts()
        except Exception:
            pass
        flash("Raw material details updated.", "success")
    except ValidationError as exc:
        db.session.rollback()
        flash(str(exc), "danger")
    return redirect(url_for("admin.material_detail", material_id=mat.id))


@admin_bp.route("/raw-materials/<int:material_id>/stock", methods=["POST"])
@admin_required
@manager_required
def record_material_stock_action(material_id):
    mat = scoped_material_or_404(material_id)
    action = (request.form.get("action") or "").strip().lower()
    valid_actions = {"add", "usage", "wastage", "damage", "expired", "return", "adjust"}
    if action not in valid_actions:
        flash("Choose a valid stock action.", "danger")
        return redirect(url_for("admin.material_detail", material_id=mat.id))
    quantity_raw = (request.form.get("quantity") or "").strip()
    try:
        quantity = Decimal(quantity_raw)
    except Exception:
        flash(f'Invalid quantity: "{quantity_raw}"', "danger")
        return redirect(url_for("admin.material_detail", material_id=mat.id))
    notes = (request.form.get("notes") or "").strip() or None
    reference_batch_id = request.form.get("reference_batch_id", type=int) or None
    inventory_service = get_container().inventory_service
    try:
        if action == "add":
            if quantity <= 0:
                raise ValidationError("Quantity must be greater than zero.")
            inventory_service.increase_raw_material_stock(
                mat,
                quantity,
                reason="manual_restock",
                created_by=current_user.id,
            )
        elif action == "usage":
            inventory_service.record_usage(
                mat,
                quantity,
                actor_id=current_user.id,
                notes=notes,
                reference_batch_id=reference_batch_id,
            )
        elif action == "wastage":
            inventory_service.record_wastage(
                mat, quantity, actor_id=current_user.id, notes=notes
            )
        elif action == "damage":
            inventory_service.record_damage(
                mat, quantity, actor_id=current_user.id, notes=notes
            )
        elif action == "expired":
            inventory_service.record_expired(
                mat, quantity, actor_id=current_user.id, notes=notes
            )
        elif action == "return":
            inventory_service.return_to_supplier(
                mat,
                quantity,
                actor_id=current_user.id,
                notes=notes,
                reference_batch_id=reference_batch_id,
            )
        elif action == "adjust":
            inventory_service.manual_adjust(
                mat, quantity, actor_id=current_user.id, notes=notes
            )
        db.session.commit()
        try:
            check_and_send_inventory_alerts()
        except Exception:
            pass
        flash("Stock updated.", "success")
    except ValidationError as exc:
        db.session.rollback()
        flash(str(exc), "danger")
    return redirect(url_for("admin.material_detail", material_id=mat.id))


@admin_bp.route("/raw-materials/<int:material_id>/batches/<int:batch_id>/status", methods=["POST"])
@admin_required
@manager_required
def set_material_batch_status(material_id, batch_id):
    mat = scoped_material_or_404(material_id)
    batch = MaterialBatch.query.filter_by(id=batch_id, raw_material_id=mat.id).first()
    if batch is None:
        flash("Batch not found.", "danger")
        return redirect(url_for("admin.material_detail", material_id=mat.id))
    status = (request.form.get("status") or "").strip().lower()
    notes = (request.form.get("notes") or "").strip() or None
    try:
        get_container().inventory_service.set_batch_status(
            batch, status, actor_id=current_user.id, notes=notes
        )
        db.session.commit()
        flash("Batch status updated.", "success")
    except ValidationError as exc:
        db.session.rollback()
        flash(str(exc), "danger")
    return redirect(url_for("admin.material_detail", material_id=mat.id))


@admin_bp.route("/raw-materials/<int:material_id>/documents", methods=["POST"])
@admin_required
@manager_required
def upload_material_document(material_id):
    mat = scoped_material_or_404(material_id)
    doc_type = (request.form.get("doc_type") or "").strip().lower()
    if doc_type not in MATERIAL_DOCUMENT_TYPE_VALUES:
        flash("Choose a valid document type.", "danger")
        return redirect(url_for("admin.material_detail", material_id=mat.id))
    file_storage = request.files.get("document")
    if file_storage is None or not getattr(file_storage, "filename", ""):
        flash("Choose a file to upload.", "danger")
        return redirect(url_for("admin.material_detail", material_id=mat.id))
    from werkzeug.utils import secure_filename

    original_filename = getattr(file_storage, "filename", "") or "document"
    safe_name = secure_filename(original_filename)
    if not safe_name:
        safe_name = "document"
    try:
        from pathlib import Path

        upload_root = (
            Path(__file__).resolve().parents[1]
            / "static"
            / "uploads"
            / "material_documents"
            / str(mat.id)
        )
        upload_root.mkdir(parents=True, exist_ok=True)
        stored_name = f"{datetime.now().strftime('%Y%m%d%H%M%S')}-{safe_name}"
        stored_path = upload_root / stored_name
        file_storage.save(str(stored_path))
        relative_path = (
            f"/static/uploads/material_documents/{mat.id}/{stored_name}"
        )
        document = MaterialDocument(
            raw_material_id=mat.id,
            purchase_order_id=request.form.get("purchase_order_id", type=int) or None,
            doc_type=doc_type,
            original_filename=original_filename[:255],
            stored_path=relative_path,
            size_bytes=os.path.getsize(str(stored_path)),
            uploaded_by=current_user.id,
        )
        db.session.add(document)
        db.session.commit()
        flash("Document uploaded.", "success")
    except Exception:
        db.session.rollback()
        flash("Document upload failed.", "danger")
    return redirect(url_for("admin.material_detail", material_id=mat.id))


@admin_bp.route("/raw-materials/documents/<int:document_id>/file")
@admin_required
@operations_required
def material_document_file(document_id):
    document = db.get_or_404(MaterialDocument, document_id)
    mat = scoped_material_or_404(document.raw_material_id)
    if mat.id != document.raw_material_id:
        abort(404)
    from pathlib import Path

    root_path = Path(__file__).resolve().parents[1]
    try:
        target = (root_path / document.stored_path.lstrip("/")).resolve()
        target.relative_to((root_path / "static").resolve())
    except (ValueError, AttributeError):
        abort(404)
    if not target.is_file():
        abort(404)
    return send_file(
        str(target),
        as_attachment=True,
        download_name=document.original_filename,
    )


@admin_bp.route("/raw-materials/<int:material_id>/toggle", methods=["POST"])
@admin_required
@manager_required
def toggle_raw_material_status(material_id):
    mat = scoped_material_or_404(material_id)
    mat.is_active = not mat.is_active
    mat.updated_by = current_user.id
    db.session.commit()
    flash(
        "Raw material " + ("enabled." if mat.is_active else "paused."),
        "success" if mat.is_active else "info",
    )
    return redirect(url_for("admin.material_detail", material_id=mat.id))


# ── COUPONS ──────────────────────────────────────────────────
@admin_bp.route("/coupons")
@admin_required
@manager_required
def coupons():
    search = (request.args.get("q") or "").strip()
    query = Coupon.query
    if search:
        query = query.filter(Coupon.code.ilike(f"%{search}%"))
    coupons = query.order_by(Coupon.id.desc()).all()
    for coupon in coupons:
        coupon.is_currently_valid = coupon.is_valid()
    return render_template(
        "admin/coupons.html",
        coupons=coupons,
        coupon_audience_choices=COUPON_AUDIENCE_CHOICES,
        search=search,
    )


@admin_bp.route("/coupons/add", methods=["POST"])
@admin_required
@manager_required
def add_coupon():
    code = request.form.get("code", "").strip().upper()
    if not code:
        flash("Coupon code is required.", "danger")
        return redirect(url_for("admin.coupons"))
    if Coupon.query.filter_by(code=code).first():
        flash("Coupon code already exists.", "warning")
        return redirect(url_for("admin.coupons"))
    try:
        discount_value = parse_decimal(
            request.form.get("discount_value"), "discount value"
        )
        min_order_value = parse_decimal(
            request.form.get("min_order_value"), "min order value"
        )
        max_uses = max(1, int(request.form.get("max_uses") or 100))
        per_user_limit = max(1, int(request.form.get("per_user_limit") or 1))
    except ValueError as e:
        flash(str(e), "danger")
        return redirect(url_for("admin.coupons"))
    customer_audience = (
        request.form.get("customer_audience") or ""
    ).strip().lower()
    if customer_audience not in COUPON_AUDIENCE_VALUES:
        flash("Please choose a valid customer condition.", "danger")
        return redirect(url_for("admin.coupons"))
    if customer_audience == COUPON_AUDIENCE_NEW_CUSTOMERS:
        per_user_limit = 1
    valid_until = None
    if request.form.get("valid_until"):
        try:
            valid_until = datetime.strptime(request.form["valid_until"], "%Y-%m-%d")
        except ValueError:
            flash("Invalid expiry date.", "danger")
            return redirect(url_for("admin.coupons"))
    db.session.add(
        Coupon(
            code=code,
            discount_type=request.form.get("discount_type", "percentage"),
            discount_value=discount_value,
            min_order_value=min_order_value,
            max_uses=max_uses,
            per_user_limit=per_user_limit,
            customer_audience=customer_audience,
            first_order_only=customer_audience == COUPON_AUDIENCE_NEW_CUSTOMERS,
            valid_until=valid_until,
        )
    )
    db.session.commit()
    flash("Coupon created!", "success")
    return redirect(url_for("admin.coupons"))


@admin_bp.route("/coupons/<int:coupon_id>/toggle", methods=["POST"])
@admin_required
@manager_required
def toggle_coupon(coupon_id):
    coupon = db.get_or_404(Coupon, coupon_id)
    coupon.is_active = not coupon.is_active
    db.session.commit()
    flash(
        f"Coupon {'enabled' if coupon.is_active else 'paused'}.",
        "success" if coupon.is_active else "info",
    )
    search = (request.args.get("q") or "").strip()
    return redirect(
        url_for("admin.coupons", q=search) if search else url_for("admin.coupons")
    )


# ── DELIVERY AGENTS ──────────────────────────────────────────
@admin_bp.route("/agents")
@admin_required
@manager_required
def agents():
    agents = (
        scoped_agent_query(
            DeliveryAgent.query.outerjoin(User, DeliveryAgent.user_id == User.id)
        )
        .order_by(
            User.is_active.desc(),
            DeliveryAgent.availability.desc(),
            DeliveryAgent.name.asc(),
        )
        .all()
    )

    active_agents = 0
    busy_agents = 0
    inactive_agents = 0
    balances = get_container().delivery_cash_service.agent_balances(
        [agent.id for agent in agents]
    )

    for agent in agents:
        open_deliveries = agent.deliveries.filter(
            Delivery.status != "DELIVERED"
        ).count()
        completed_deliveries = agent.deliveries.filter(
            Delivery.status == "DELIVERED"
        ).count()
        agent.open_delivery_count = open_deliveries
        agent.completed_delivery_count = completed_deliveries
        agent.cash_balance = balances.get(agent.id, Decimal("0.00"))

        if agent.user and agent.user.is_active:
            active_agents += 1
            if not agent.availability or open_deliveries:
                busy_agents += 1
        else:
            inactive_agents += 1

    stats = {
        "total": len(agents),
        "active": active_agents,
        "busy": busy_agents,
        "inactive": inactive_agents,
    }
    return render_template("admin/agents.html", agents=agents, stats=stats)


@admin_bp.route("/agents/add", methods=["POST"])
@admin_required
@owner_required
def add_agent():
    name = (request.form.get("name") or "").strip()
    phone = (request.form.get("phone") or "").strip()
    email = (request.form.get("email") or "").strip().lower()
    password = (request.form.get("password") or "").strip()

    if len(name) < 2:
        flash("Agent name must be at least 2 characters.", "danger")
        return redirect(url_for("admin.agents"))
    if not phone:
        flash("Phone number is required.", "danger")
        return redirect(url_for("admin.agents"))
    if not email:
        flash("Email is required.", "danger")
        return redirect(url_for("admin.agents"))
    password_errors = validate_password(password)
    if password_errors:
        for err in password_errors:
            flash(err, "danger")
        return redirect(url_for("admin.agents"))
    if User.query.filter_by(email=email).first():
        flash("That email is already in use.", "danger")
        return redirect(url_for("admin.agents"))

    user = User(
        name=name,
        email=email,
        phone=phone,
        role="delivery",
        is_active=True,
        branch_id=current_admin_branch_id(),
    )
    user.set_password(password, require_change=True)
    db.session.add(user)
    db.session.flush()
    db.session.add(
        DeliveryAgent(
            user_id=user.id,
            branch_id=current_admin_branch_id(),
            name=name,
            phone=phone,
            availability=True,
        )
    )
    db.session.commit()
    from app import record_development_credential

    record_development_credential(
        "delivery",
        email,
        password,
        label=f"Delivery Account ({name})",
        source="admin_created",
    )
    if current_app.config.get("SHOW_DEMO_ACCOUNTS", False):
        flash(
            f"Delivery account created for {name}. Credentials: {email} / {password}",
            "success",
        )
        current_app.logger.info(
            "Delivery credentials created: %s / %s", email, password
        )
    else:
        flash(f"Delivery account created for {name}.", "success")
        current_app.logger.info("Delivery account created: %s", email)
    return redirect(url_for("admin.agents"))


@admin_bp.route("/agents/<int:agent_id>/reset-password", methods=["POST"])
@admin_required
@owner_required
def reset_agent_password(agent_id):
    agent = scoped_agent_or_404(agent_id)
    if agent.user is None:
        flash("This delivery profile is not linked to a login account yet.", "danger")
        return redirect(url_for("admin.agents"))

    password = (request.form.get("password") or "").strip()
    password_errors = validate_password(password)
    if password_errors:
        for err in password_errors:
            flash(err, "danger")
        return redirect(url_for("admin.agents"))

    agent.user.set_password(password, require_change=True)
    agent.user.is_active = True
    db.session.commit()

    from app import record_development_credential

    record_development_credential(
        "delivery",
        agent.user.email,
        password,
        label=f"Delivery Account ({agent.name})",
        source="admin_reset",
    )
    if current_app.config.get("SHOW_DEMO_ACCOUNTS", False):
        flash(
            f"Password reset for {agent.name}. Credentials: {agent.user.email} / {password}",
            "success",
        )
        current_app.logger.info(
            "Delivery credentials reset: %s / %s", agent.user.email, password
        )
    else:
        flash(f"Password reset for {agent.name}.", "success")
        current_app.logger.info("Delivery password reset: %s", agent.user.email)
    return redirect(url_for("admin.agents"))


@admin_bp.route("/agents/<int:agent_id>/toggle-access", methods=["POST"])
@admin_required
@owner_required
def toggle_agent_access(agent_id):
    agent = scoped_agent_or_404(agent_id)
    if agent.user is None:
        flash("This delivery profile is not linked to a login account yet.", "danger")
        return redirect(url_for("admin.agents"))

    previous_active = agent.user.is_active
    agent.user.is_active = not agent.user.is_active
    if not agent.user.is_active:
        agent.availability = False
        flash(f"{agent.name} has been deactivated.", "warning")
    else:
        has_open_delivery = (
            agent.deliveries.filter(Delivery.status != "DELIVERED").first() is not None
        )
        agent.availability = not has_open_delivery
        flash(f"{agent.name} has been reactivated.", "success")

    db.session.commit()
    get_container().audit_service.log(
        current_user,
        "user_access_changed",
        "User",
        agent.user.id,
        before={"is_active": previous_active, "role": agent.user.role},
        after={"is_active": agent.user.is_active, "role": agent.user.role},
        change_summary=f"Delivery access toggled for {agent.name}",
    )
    return redirect(url_for("admin.agents"))


# ── ANALYTICS ────────────────────────────────────────────────
@admin_bp.route("/analytics")
@admin_required
@manager_required
def analytics():
    selected_period = (request.args.get("period") or "month").strip().lower()
    if selected_period not in PERIOD_LABELS:
        selected_period = "month"
    selected_granularity = request.args.get("granularity") or default_granularity(
        selected_period
    )
    selected_payload = analytics_payload(
        selected_period, granularity=selected_granularity
    )
    period_keys = ["today", "week", "month", "year"]

    return render_template(
        "admin/analytics.html",
        revenue_cards=[
            {
                "period": period,
                "label": PERIOD_LABELS[period],
                "revenue": float(total_revenue(period)),
            }
            for period in period_keys
        ],
        best_sellers={period: top_selling_product(period) for period in period_keys},
        selected_period=selected_period,
        selected_payload=selected_payload,
        period_labels=PERIOD_LABELS,
    )


@admin_bp.route("/api/analytics/revenue")
@admin_required
@manager_required
def analytics_revenue_api():
    period = (request.args.get("period") or "month").strip().lower()
    start_date = request.args.get("start_date")
    end_date = request.args.get("end_date")
    if start_date or end_date:
        period = "custom"
    granularity = request.args.get("granularity") or default_granularity(period)

    try:
        payload = analytics_payload(
            period,
            granularity=granularity,
            start_date=start_date,
            end_date=end_date,
        )
    except ValueError as exc:
        return jsonify({"ok": False, "message": str(exc)}), 400
    return jsonify({"ok": True, **payload})


@admin_bp.route("/security")
@admin_required
@owner_required
def security_admin():
    recent_events = SecurityEvent.query.order_by(SecurityEvent.created_at.desc()).limit(50).all()
    webhook_failures = (
        WebhookEventLog.query.filter(WebhookEventLog.signature_status != "valid")
        .order_by(WebhookEventLog.received_at.desc())
        .limit(25)
        .all()
    )
    locked_users = (
        User.query.filter(
            User.is_active.is_(True),
            or_(User.email_locked.is_(True), User.force_logout_before.isnot(None)),
        )
        .order_by(User.updated_at.desc() if hasattr(User, "updated_at") else User.created_at.desc())
        .limit(25)
        .all()
    )
    recent_logins = (
        LoginHistory.query.order_by(LoginHistory.login_time.desc())
        .limit(60)
        .all()
    )
    return render_template(
        "admin/security.html",
        infrastructure=get_container().security_service.infrastructure_status(),
        recent_events=recent_events,
        webhook_failures=webhook_failures,
        locked_users=locked_users,
        recent_logins=recent_logins,
    )


@admin_bp.route("/notifications", methods=["GET", "POST"])
@admin_required
@manager_required
def notifications_admin():
    if request.method == "POST":
        try:
            template = get_container().notification_engine.upsert_template(
                event_type=request.form.get("event_type"),
                channel=request.form.get("channel"),
                name=request.form.get("name"),
                subject=request.form.get("subject"),
                body=request.form.get("body"),
                provider_template_id=request.form.get("provider_template_id"),
                actor_id=current_user.id,
            )
            get_container().audit_service.log(
                current_user,
                "notification_template_changed",
                "NotificationTemplate",
                template.event_type,
                after={
                    "channel": template.channel,
                    "version": template.version,
                    "provider_template_id": template.provider_template_id,
                },
                change_summary=f"Notification template {template.event_type}/{template.channel} updated.",
            )
            db.session.commit()
            flash("Notification template saved.", "success")
        except ValidationError as exc:
            db.session.rollback()
            flash(str(exc), "danger")
        return redirect(url_for("admin.notifications_admin"))

    templates = (
        NotificationTemplate.query.order_by(
            NotificationTemplate.event_type.asc(),
            NotificationTemplate.channel.asc(),
            NotificationTemplate.version.desc(),
        )
        .limit(200)
        .all()
    )
    logs = (
        NotificationDeliveryLog.query.order_by(NotificationDeliveryLog.queued_at.desc())
        .limit(100)
        .all()
    )
    kitchen_alerts = (
        KitchenAlert.query.order_by(KitchenAlert.created_at.desc()).limit(50).all()
    )
    return render_template(
        "admin/notifications.html",
        templates=templates,
        logs=logs,
        kitchen_alerts=kitchen_alerts,
    )


@admin_bp.route("/table-qr", methods=["GET", "POST"])
@admin_required
@manager_required
def table_qr():
    if request.method == "POST":
        try:
            branch_id = request.form.get("branch_id", type=int)
            scoped_branch_or_404(branch_id)
            area_name = (request.form.get("area_name") or "").strip()
            area = None
            if area_name:
                area = get_container().table_qr_service.create_area(
                    branch_id=branch_id,
                    name=area_name,
                )
                db.session.flush()
            table = get_container().table_qr_service.create_table(
                branch_id=branch_id,
                table_number=request.form.get("table_number"),
                display_name=request.form.get("display_name"),
                area_id=area.id if area else request.form.get("area_id", type=int),
                seating_capacity=request.form.get("seating_capacity", type=int) or 2,
                notes=request.form.get("notes"),
            )
            get_container().audit_service.log(
                current_user,
                "qr_table_created",
                "DiningTable",
                table.table_number,
                after={
                    "branch_id": branch_id,
                    "display_name": table.display_name,
                    "area_id": table.area_id,
                },
                change_summary=f"Table QR created for {table.display_name}.",
            )
            db.session.commit()
            flash("Table QR code created.", "success")
        except ValidationError as exc:
            db.session.rollback()
            flash(str(exc), "danger")
        return redirect(url_for("admin.table_qr"))

    table_query = scope_query_to_admin_branch(
        DiningTable.query,
        DiningTable.branch_id,
        include_unassigned=False,
    )
    tables = table_query.order_by(DiningTable.branch_id.asc(), DiningTable.table_number.asc()).all()
    for table in tables:
        table.qr_data_uri = get_container().table_qr_service.build_qr_data_uri(table)
        table.qr_url = get_container().table_qr_service.table_url(table)
        table.scan_count = table.menu_scans.count()
        table.order_count = Order.query.filter_by(dining_table_id=table.id).count()
    branches = scoped_branch_query().order_by(Branch.name.asc()).all()
    areas = scope_query_to_admin_branch(
        DiningArea.query,
        DiningArea.branch_id,
        include_unassigned=False,
    ).order_by(DiningArea.name.asc()).all()
    return render_template(
        "admin/table_qr.html",
        tables=tables,
        branches=branches,
        areas=areas,
    )


@admin_bp.route("/table-qr/<int:table_id>/regenerate", methods=["POST"])
@admin_required
@manager_required
def regenerate_table_qr(table_id):
    table = db.get_or_404(DiningTable, table_id)
    abort_if_no_branch_access(table.branch_id)
    before = {"qr_token": "redacted", "last_regenerated_at": table.last_regenerated_at}
    get_container().table_qr_service.regenerate_token(table)
    get_container().audit_service.log(
        current_user,
        "qr_token_regenerated",
        "DiningTable",
        table.id,
        before=before,
        after={"qr_token": "redacted", "last_regenerated_at": table.last_regenerated_at},
        change_summary=f"QR token regenerated for {table.display_name}.",
    )
    db.session.commit()
    flash("QR token regenerated. Reprint the table code.", "success")
    return redirect(url_for("admin.table_qr"))


@admin_bp.route("/table-qr/<int:table_id>/status", methods=["POST"])
@admin_required
@manager_required
def update_table_qr_status(table_id):
    table = db.get_or_404(DiningTable, table_id)
    abort_if_no_branch_access(table.branch_id)
    status = (request.form.get("status") or "").strip().lower()
    if status not in {"active", "inactive", "occupied", "available", "temporarily_unavailable"}:
        flash("Unsupported table status.", "danger")
        return redirect(url_for("admin.table_qr"))
    before = {"status": table.status}
    table.status = status
    table.updated_at = utcnow()
    get_container().audit_service.log(
        current_user,
        "qr_table_status_changed",
        "DiningTable",
        table.id,
        before=before,
        after={"status": status},
        change_summary=f"Table {table.display_name} status changed to {status}.",
    )
    db.session.commit()
    flash("Table status updated.", "success")
    return redirect(url_for("admin.table_qr"))


# ── CATEGORIES ───────────────────────────────────────────────
@admin_bp.route("/categories")
@admin_required
@manager_required
def categories():
    cats = Category.query.order_by(Category.name.asc()).all()
    category_cards = []
    for category in cats:
        products = (
            category.products.order_by(Product.is_active.desc(), Product.name.asc()).all()
        )
        category_cards.append(
            {
                "category": category,
                "products": products,
                "total_count": len(products),
                "active_count": sum(1 for product in products if product.is_active),
            }
        )
    return render_template(
        "admin/categories.html",
        cats=cats,
        category_cards=category_cards,
    )


@admin_bp.route("/categories/add", methods=["POST"])
@admin_required
@manager_required
def add_category():
    name = request.form.get("name", "").strip()
    icon = request.form.get("icon", "🎂")
    if not name:
        flash("Category name is required.", "danger")
        return redirect(url_for("admin.categories"))
    if Category.query.filter_by(name=name).first():
        flash("That category already exists.", "warning")
        return redirect(url_for("admin.categories"))

    category = Category(name=name, icon=icon)
    try:
        apply_category_image(category)
        db.session.add(category)
        db.session.commit()
    except ValidationError as exc:
        db.session.rollback()
        flash(str(exc), "danger")
        return redirect(url_for("admin.categories"))

    flash("Category added!", "success")
    return redirect(url_for("admin.categories"))


# ── LOYALTY ADMIN ────────────────────────────────────────────
@admin_bp.route("/loyalty")
@admin_required
@manager_required
def loyalty():
    """Loyalty points leaderboard + adjustment panel."""
    top_users = (
        db.session.query(User, func.sum(LoyaltyLedger.points).label("total_pts"))
        .join(LoyaltyLedger, LoyaltyLedger.user_id == User.id)
        .filter(User.role == "customer")
        .group_by(User.id)
        .order_by(func.sum(LoyaltyLedger.points).desc())
        .limit(50)
        .all()
    )

    total_issued = (
        db.session.query(func.coalesce(func.sum(LoyaltyLedger.points), 0))
        .filter(LoyaltyLedger.points > 0)
        .scalar()
        or 0
    )
    total_redeemed = abs(
        db.session.query(func.coalesce(func.sum(LoyaltyLedger.points), 0))
        .filter(LoyaltyLedger.points < 0)
        .scalar()
        or 0
    )
    return render_template(
        "admin/loyalty.html",
        top_users=top_users,
        total_issued=int(total_issued),
        total_redeemed=int(total_redeemed),
        loyalty_config=get_loyalty_config(),
    )


@admin_bp.route("/loyalty/adjust", methods=["POST"])
@admin_required
@manager_required
def loyalty_adjust():
    user_id = request.form.get("user_id", type=int)
    points = request.form.get("points", type=int)
    reason = (request.form.get("reason") or "").strip()
    if not user_id or points is None:
        flash("User and points are required.", "danger")
        return redirect(url_for("admin.loyalty"))
    if not reason:
        flash("A reason is required for loyalty adjustments.", "danger")
        return redirect(url_for("admin.loyalty"))
    user = db.get_or_404(User, user_id)
    before_points = user.loyalty_points
    try:
        get_container().loyalty_service.adjust_points(user_id, points, reason)
    except ValueError as exc:
        flash(str(exc), "danger")
        return redirect(url_for("admin.loyalty"))
    notify(
        user_id,
        "Loyalty Points Updated",
        f"Your points have been adjusted by {points:+d} by the bakery.",
        "loyalty",
    )
    get_container().audit_service.log(
        current_user,
        "loyalty_points_adjusted",
        "User",
        user_id,
        before={"loyalty_balance": before_points},
        after={
            "loyalty_balance": user.loyalty_points,
            "delta": points,
            "reason": reason,
        },
        change_summary=f"Loyalty adjusted by {points:+d} for {user.name}",
    )
    db.session.commit()
    flash(f"Adjusted {points:+d} pts for {user.name}.", "success")
    return redirect(url_for("admin.loyalty"))


# ── GIFT CARDS ───────────────────────────────────────────────
@admin_bp.route("/gift-cards")
@admin_required
@manager_required
def gift_cards():
    cards = (
        GiftCard.query.order_by(GiftCard.issued_at.desc(), GiftCard.id.desc())
        .limit(250)
        .all()
    )
    for card in cards:
        card.recent_transactions = (
            card.transactions.order_by(GiftCardTransaction.created_at.desc())
            .limit(4)
            .all()
        )
    liability = get_container().gift_card_service.outstanding_liability()
    return render_template(
        "admin/gift_cards.html",
        cards=cards,
        liability=liability,
    )


@admin_bp.route("/gift-cards/issue", methods=["POST"])
@admin_required
@manager_required
def issue_gift_card():
    amount = request.form.get("amount", "0")
    recipient_email = (request.form.get("recipient_email") or "").strip()
    message = (request.form.get("message") or "").strip()
    try:
        with db.session.begin_nested():
            card = get_container().gift_card_service.issue(
                amount=amount,
                recipient_email=recipient_email,
                message=message,
                actor_id=current_user.id,
                reason="counter_gift_card_issue",
            )
            get_container().audit_service.log(
                current_user.id,
                "gift_card_issued",
                "GiftCard",
                card.id,
                before=None,
                after={
                    "code": card.code,
                    "initial_value": str(card.initial_value),
                    "recipient_email": card.recipient_email,
                },
                change_summary=f"Gift card {card.code} issued.",
            )
        db.session.commit()
        flash(f"Gift card {card.code} issued.", "success")
    except ValidationError as exc:
        db.session.rollback()
        flash(str(exc), "danger")
    return redirect(request.referrer or url_for("admin.gift_cards"))


@admin_bp.route("/gift-cards/<int:card_id>/adjust", methods=["POST"])
@admin_required
@manager_required
def adjust_gift_card(card_id):
    card = db.get_or_404(GiftCard, card_id)
    reason = (request.form.get("reason") or "").strip()
    before = {"balance": str(card.current_balance), "status": card.status}
    try:
        with db.session.begin_nested():
            get_container().gift_card_service.manual_adjust(
                card,
                request.form.get("amount_change", "0"),
                reason=reason,
                actor_id=current_user.id,
            )
            get_container().audit_service.log(
                current_user.id,
                "gift_card_adjusted",
                "GiftCard",
                card.id,
                before=before,
                after={"balance": str(card.current_balance), "status": card.status},
                change_summary=f"Gift card {card.code} adjusted: {reason}",
            )
        db.session.commit()
        flash("Gift card balance adjusted.", "success")
    except ValidationError as exc:
        db.session.rollback()
        flash(str(exc), "danger")
    return redirect(url_for("admin.gift_cards"))


@admin_bp.route("/gift-cards/<int:card_id>/cancel", methods=["POST"])
@admin_required
@manager_required
def cancel_gift_card(card_id):
    card = db.get_or_404(GiftCard, card_id)
    reason = (request.form.get("reason") or "").strip()
    before = {"balance": str(card.current_balance), "status": card.status}
    try:
        with db.session.begin_nested():
            get_container().gift_card_service.cancel(
                card,
                reason=reason,
                actor_id=current_user.id,
            )
            get_container().audit_service.log(
                current_user.id,
                "gift_card_cancelled",
                "GiftCard",
                card.id,
                before=before,
                after={"balance": str(card.current_balance), "status": card.status},
                change_summary=f"Gift card {card.code} cancelled: {reason}",
            )
        db.session.commit()
        flash("Gift card cancelled.", "success")
    except ValidationError as exc:
        db.session.rollback()
        flash(str(exc), "danger")
    return redirect(url_for("admin.gift_cards"))


@admin_bp.route("/pos/gift-card", methods=["POST"])
@admin_required
@manager_required
def pos_gift_card():
    return issue_gift_card()


@admin_bp.route("/pos/variants/<int:variant_id>/availability", methods=["POST"])
@admin_required
@operations_required
def update_pos_variant_availability(variant_id):
    variant = scoped_variant_or_404(variant_id)
    product = variant.product
    stock = max(0, request.form.get("stock", type=int) or 0)
    expected_version = request.form.get("expected_version")
    kitchen_note = (request.form.get("preparation") or "").strip()
    from utils.optimistic import assert_version

    try:
        assert_version(variant, expected_version, entity_name="ProductVariant")
        before = {
            "stock": variant.stock,
            "version": variant.version,
            "preparation": product.preparation,
        }
        variant.stock = stock
        variant.version = int(variant.version or 0) + 1
        product.preparation = kitchen_note or None
        get_container().audit_service.log(
            current_user,
            "walkin_product_availability_updated",
            "ProductVariant",
            variant.id,
            before=before,
            after={
                "stock": variant.stock,
                "version": variant.version,
                "preparation": product.preparation,
            },
            change_summary=f"Walk-in availability updated for {product.name}.",
        )
        db.session.commit()
        get_container().offline_sync_service.cache_variant(variant)
        emit_stock_updated(variant, include_customer=True)
        flash("Walk-in product availability updated.", "success")
    except (ConflictError, ValidationError) as exc:
        db.session.rollback()
        flash(str(exc), "danger")
    except SQLAlchemyError:
        db.session.rollback()
        flash("Could not update product availability right now.", "danger")
    return redirect(url_for("admin.pos"))


# ── INVENTORY ALERT TRIGGER (manual) ─────────────────────────
@admin_bp.route("/inventory/send-alerts", methods=["POST"])
@admin_required
@operations_required
def send_inventory_alerts():
    try:
        check_and_send_inventory_alerts()
        flash("Inventory alert emails sent to admins.", "success")
    except Exception as e:
        flash(f"Alert failed: {e}", "danger")
    return redirect(url_for("admin.inventory"))


@admin_bp.route("/forecasts")
@admin_required
@manager_required
def forecasts():
    return render_template("admin/forecasts.html")


KDS_QUEUE_STATUSES = ("PLACED", "PREPARING")
KDS_PRIORITY_KEYWORDS = ("priority", "urgent", "rush", "asap")


def _kds_order_age_minutes(order, now):
    if not order.placed_at:
        return 0
    return max(0, int((now - order.placed_at).total_seconds() // 60))


def _delivery_slot_start_minutes(slot):
    if not slot:
        return None
    start = slot.split("-")[0].strip()
    if ":" not in start:
        return None
    hour_text, minute_text = start.split(":", 1)
    try:
        hour = int(hour_text)
        minute = int(minute_text[:2])
    except ValueError:
        return None
    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        return None
    return hour * 60 + minute


def _kds_priority_reasons(order, now):
    reasons = []
    note_text = f"{order.special_note or ''} {order.occasion or ''}".lower()
    if any(keyword in note_text for keyword in KDS_PRIORITY_KEYWORDS):
        reasons.append("Priority note")

    age_minutes = _kds_order_age_minutes(order, now)
    if order.status == "PLACED" and age_minutes >= 20:
        reasons.append(f"Not started for {age_minutes} min")
    elif age_minutes >= 45:
        reasons.append(f"Waiting {age_minutes} min")

    today = now.date()
    if order.delivery_date:
        if order.delivery_date < today:
            reasons.append("Delivery date overdue")
        elif order.delivery_date == today:
            slot_start = _delivery_slot_start_minutes(order.delivery_slot)
            if slot_start is None:
                reasons.append("Due today")
            else:
                now_minutes = now.hour * 60 + now.minute
                if slot_start - now_minutes <= 90:
                    reasons.append("Delivery slot soon")
    return reasons


@admin_bp.route("/kds")
@admin_required
@operations_required
def kitchen_display():
    now = utcnow()
    orders = (
        scoped_order_query(
            Order.query.filter(Order.status.in_(KDS_QUEUE_STATUSES)),
            include_unassigned=True,
        )
        .order_by(Order.placed_at.asc())
        .all()
    )
    priority_orders = []
    queue_orders = []
    for order in orders:
        order.kds_age_minutes = _kds_order_age_minutes(order, now)
        order.kds_priority_reasons = _kds_priority_reasons(order, now)
        if order.kds_priority_reasons:
            priority_orders.append(order)
        else:
            queue_orders.append(order)

    return render_template(
        "admin/kds.html",
        priority_orders=priority_orders,
        queue_orders=queue_orders,
        total_queue_count=len(orders),
        now=now,
    )


@admin_bp.route("/staff")
@admin_required
@owner_required
def staff():
    staff_users = (
        User.query.filter(
            User.role.in_(
                ("admin", "super_admin", "branch_manager", "cashier", "kitchen_staff")
            )
        )
        .order_by(User.is_active.desc(), User.admin_tier.desc(), User.name.asc())
        .all()
    )
    annotate_staff_access(staff_users)
    shifts = StaffShift.query.order_by(StaffShift.shift_date.desc()).limit(20).all()
    attendance = (
        AttendanceRecord.query.order_by(AttendanceRecord.created_at.desc())
        .limit(20)
        .all()
    )
    salaries = (
        SalaryRecord.query.order_by(SalaryRecord.period_end.desc()).limit(20).all()
    )
    branches = Branch.query.order_by(Branch.name.asc()).all()
    return render_template(
        "admin/staff.html",
        staff_users=staff_users,
        shifts=shifts,
        attendance=attendance,
        salaries=salaries,
        branches=branches,
        tier_options=["manager", "staff"],
        edit_tier_options=["owner", "manager", "staff"],
        staff_role_choices=STAFF_PORTAL_ROLE_CHOICES,
        staff_access_choices=STAFF_PORTAL_ACCESS_CHOICES,
    )


@admin_bp.route("/staff/add", methods=["POST"])
@admin_required
@owner_required
def add_staff_member():
    name = (request.form.get("name") or "").strip()
    email = (request.form.get("email") or "").strip().lower()
    phone = (request.form.get("phone") or "").strip()
    password = (request.form.get("password") or "").strip()
    role = (request.form.get("role") or "admin").strip().lower()
    admin_tier = (request.form.get("admin_tier") or "staff").strip().lower()
    branch_id = request.form.get("branch_id", type=int)
    if role not in STAFF_PORTAL_ROLE_VALUES:
        flash("Choose a valid staff role.", "danger")
        return redirect(url_for("admin.staff"))
    if admin_tier not in {"manager", "staff"}:
        admin_tier = "staff"
    if role in BRANCH_EMPLOYEE_ROLE_VALUES:
        admin_tier = branch_employee_admin_tier(role)
    if not name or not email or not password:
        flash("Name, email, and password are required.", "danger")
        return redirect(url_for("admin.staff"))
    if User.query.filter_by(email=email).first():
        flash("A user with that email already exists.", "warning")
        return redirect(url_for("admin.staff"))
    if branch_id and db.session.get(Branch, branch_id) is None:
        flash("Choose a valid branch.", "danger")
        return redirect(url_for("admin.staff"))
    password_errors = validate_password(password)
    if password_errors:
        for error in password_errors:
            flash(error, "danger")
        return redirect(url_for("admin.staff"))
    user = User(
        name=name,
        email=email,
        phone=phone,
        role=role,
        admin_tier=admin_tier,
        branch_id=branch_id,
        is_active=True,
        email_locked=True,
    )
    try:
        apply_staff_profile_from_form(user, role)
    except ValidationError as exc:
        flash(str(exc), "danger")
        return redirect(url_for("admin.staff"))
    user.set_password(password, require_change=True)
    db.session.add(user)
    db.session.flush()
    get_container().audit_service.log(
        current_user,
        "admin_staff_created",
        "User",
        user.id,
        after={
            "email": user.email,
            "role": user.role,
            "admin_tier": user.admin_tier,
            "branch_id": user.branch_id,
            "is_active": user.is_active,
            "staff_address": user.staff_address,
            "date_of_joining": (
                user.date_of_joining.isoformat() if user.date_of_joining else None
            ),
            "designation": user.designation,
            "emergency_contact": user.emergency_contact,
            "staff_notes": user.staff_notes,
            "email_locked": user.email_locked,
            "portal_access": staff_portal_access_values(user),
        },
        change_summary=f"Admin portal account created for {name}.",
    )
    db.session.commit()
    role_label = STAFF_PORTAL_ROLE_LABELS.get(role, role.replace("_", " ").title())
    flash(f"{name} added as {role_label}. First login will require a password change.", "success")
    return redirect(url_for("admin.staff"))


def _active_owner_count(excluding_user_id=None):
    query = User.query.filter(
        User.is_active == True,
        User.role.in_(("admin", "super_admin")),
    )
    owners = [
        user
        for user in query.all()
        if user.effective_admin_tier == "owner"
        and (excluding_user_id is None or user.id != excluding_user_id)
    ]
    return len(owners)


@admin_bp.route("/staff/<int:user_id>/tier", methods=["POST"])
@admin_required
@owner_required
def update_staff_tier(user_id):
    user = db.get_or_404(User, user_id)
    if not has_role(user, *ADMIN_PORTAL_ROLES):
        flash("Only admin-portal accounts can receive admin tiers.", "danger")
        return redirect(url_for("admin.staff"))
    if not has_role(user, "admin", "super_admin"):
        flash("Branch staff access level is controlled by their assigned role.", "info")
        return redirect(url_for("admin.staff"))
    new_tier = (request.form.get("admin_tier") or "staff").strip().lower()
    if new_tier not in {"owner", "manager", "staff"}:
        flash("Choose a valid admin tier.", "danger")
        return redirect(url_for("admin.staff"))
    previous = {
        "role": user.role,
        "admin_tier": user.effective_admin_tier,
        "is_active": user.is_active,
    }
    if user.id == current_user.id and new_tier != "owner":
        flash("You cannot remove owner access from your own account.", "warning")
        return redirect(url_for("admin.staff"))
    if (
        user.effective_admin_tier == "owner"
        and new_tier != "owner"
        and _active_owner_count(user.id) == 0
    ):
        flash("At least one active owner account is required.", "warning")
        return redirect(url_for("admin.staff"))
    user.role = "admin"
    user.admin_tier = new_tier
    get_container().audit_service.log(
        current_user,
        "admin_tier_changed",
        "User",
        user.id,
        before=previous,
        after={
            "role": user.role,
            "admin_tier": user.admin_tier,
            "is_active": user.is_active,
        },
        change_summary=f"Admin tier changed for {user.email}.",
    )
    db.session.commit()
    flash(f"{user.name}'s admin tier is now {new_tier}.", "success")
    return redirect(url_for("admin.staff"))


@admin_bp.route("/staff/<int:user_id>/toggle", methods=["POST"])
@admin_required
@owner_required
def toggle_staff_access(user_id):
    user = db.get_or_404(User, user_id)
    if not has_role(user, *ADMIN_PORTAL_ROLES):
        flash("Only admin-portal accounts can be managed here.", "danger")
        return redirect(url_for("admin.staff"))
    if user.id == current_user.id:
        flash("You cannot deactivate your own account.", "warning")
        return redirect(url_for("admin.staff"))
    if (
        user.is_active
        and user.effective_admin_tier == "owner"
        and _active_owner_count(user.id) == 0
    ):
        flash("At least one active owner account is required.", "warning")
        return redirect(url_for("admin.staff"))
    previous = {
        "is_active": user.is_active,
        "admin_tier": user.effective_admin_tier,
        "role": user.role,
    }
    user.is_active = not user.is_active
    get_container().audit_service.log(
        current_user,
        "admin_staff_access_changed",
        "User",
        user.id,
        before=previous,
        after={
            "is_active": user.is_active,
            "admin_tier": user.effective_admin_tier,
            "role": user.role,
        },
        change_summary=f"Admin portal access toggled for {user.email}.",
    )
    db.session.commit()
    flash(
        f"{user.name} {'reactivated' if user.is_active else 'deactivated'}.",
        "success" if user.is_active else "warning",
    )
    return redirect(url_for("admin.staff"))


@admin_bp.route("/staff/shifts/add", methods=["POST"])
@admin_required
@owner_required
def add_staff_shift():
    user_id = request.form.get("user_id", type=int)
    shift_date_raw = request.form.get("shift_date", "").strip()
    start_time_raw = request.form.get("start_time", "").strip()
    end_time_raw = request.form.get("end_time", "").strip()
    user = db.get_or_404(User, user_id)
    try:
        shift_date = datetime.strptime(shift_date_raw, "%Y-%m-%d").date()
        start_time_value = datetime.strptime(start_time_raw, "%H:%M").time()
        end_time_value = datetime.strptime(end_time_raw, "%H:%M").time()
    except ValueError:
        flash("Invalid shift date or time.", "danger")
        return redirect(url_for("admin.staff"))
    db.session.add(
        StaffShift(
            user_id=user.id,
            branch_id=user.branch_id,
            role=user.role,
            shift_date=shift_date,
            start_time=start_time_value,
            end_time=end_time_value,
        )
    )
    db.session.commit()
    flash("Shift scheduled.", "success")
    return redirect(url_for("admin.staff"))


@admin_bp.route("/staff/attendance/clock", methods=["POST"])
@admin_required
@owner_required
def clock_staff_attendance():
    user_id = request.form.get("user_id", type=int)
    action = (request.form.get("action") or "in").strip().lower()
    user = db.get_or_404(User, user_id)
    record = (
        AttendanceRecord.query.filter_by(user_id=user.id)
        .order_by(AttendanceRecord.created_at.desc())
        .first()
    )
    if action == "in":
        db.session.add(
            AttendanceRecord(
                user_id=user.id,
                branch_id=user.branch_id,
                clock_in_at=utcnow(),
                status="present",
            )
        )
        flash("Clock-in recorded.", "success")
    else:
        if (
            record is None
            or record.clock_in_at is None
            or record.clock_out_at is not None
        ):
            flash("No open attendance record found.", "warning")
            return redirect(url_for("admin.staff"))
        record.clock_out_at = utcnow()
        record.worked_minutes = int(
            (record.clock_out_at - record.clock_in_at).total_seconds() // 60
        )
        flash("Clock-out recorded.", "success")
    db.session.commit()
    return redirect(url_for("admin.staff"))


POS_MVP_PAYMENT_METHOD_LABELS = {
    "CASH": "Cash",
    "UPI": "UPI",
    "CREDIT_CARD": "Credit Card",
    "DEBIT_CARD": "Debit Card",
    "BANK_TRANSFER": "Bank Transfer",
    "OTHER": "Other",
}


@admin_bp.route("/pos/terminal", methods=["GET", "POST"])
@admin_required
@operations_required
def pos_terminal():
    selected_order = None
    order_number = (request.values.get("order_number") or "").strip()
    if order_number:
        selected_order = Order.query.filter_by(order_number=order_number).first()
        if selected_order is not None:
            abort_if_no_branch_access(selected_order.branch_id, include_unassigned=True)

    if request.method == "POST":
        idempotency_key = (request.form.get("idempotency_key") or "").strip()
        terminal_branch_id = current_admin_branch_id()
        if terminal_branch_id is None:
            configured_branch_id = current_app.config.get("DEFAULT_BRANCH_ID")
            terminal_branch_id = (
                configured_branch_id
                if configured_branch_id and db.session.get(Branch, configured_branch_id)
                else None
            )
        try:
            transaction, created = get_container().payment_service.record_pos_mvp_payment(
                amount=request.form.get("amount"),
                payment_method=request.form.get("payment_method"),
                cashier_id=current_user.id,
                branch_id=terminal_branch_id,
                order_id=request.form.get("order_id", type=int),
                order_number=request.form.get("order_number"),
                cash_received=request.form.get("cash_received"),
                transaction_reference=request.form.get("transaction_reference"),
                upi_app=request.form.get("upi_app"),
                card_last4=request.form.get("card_last4"),
                card_type=request.form.get("card_type"),
                bank_name=request.form.get("bank_name"),
                payment_date=request.form.get("payment_date"),
                other_note=request.form.get("other_note"),
                notes=request.form.get("notes"),
                idempotency_key=idempotency_key,
                transaction_limit=current_app.config.get("POS_MVP_TRANSACTION_LIMIT", 100000),
            )
            get_container().audit_service.log(
                current_user,
                "pos_mvp_payment_completed",
                "PosPaymentTransaction",
                transaction.id,
                after={
                    "transaction_id": transaction.transaction_id,
                    "order_id": transaction.order_id,
                    "amount": str(transaction.amount),
                    "payment_method": transaction.payment_method,
                    "payment_status": transaction.payment_status,
                    "created": created,
                },
                branch_id=transaction.branch_id,
                request_id=f"pos-mvp-completed-{idempotency_key}",
                change_summary=f"POS payment {transaction.transaction_id} completed.",
            )
            db.session.commit()
            return redirect(url_for("admin.pos_terminal_success", transaction_id=transaction.id))
        except ValidationError as exc:
            db.session.rollback()
            try:
                get_container().audit_service.log(
                    current_user,
                    "pos_mvp_payment_failed",
                    "PosPaymentTransaction",
                    idempotency_key or "missing",
                    after={
                        "amount": request.form.get("amount"),
                        "payment_method": request.form.get("payment_method"),
                        "order_number": request.form.get("order_number"),
                        "reason": str(exc),
                    },
                    branch_id=current_admin_branch_id(),
                    request_id=f"pos-mvp-failed-{idempotency_key or secrets.token_urlsafe(8)}",
                    change_summary="POS payment attempt failed validation.",
                )
                db.session.commit()
            except Exception:
                db.session.rollback()
            flash(str(exc), "danger")
        except SQLAlchemyError:
            db.session.rollback()
            flash("Unable to record this payment right now.", "danger")

    recent_transactions = (
        PosPaymentTransaction.query.order_by(PosPaymentTransaction.created_at.desc())
        .limit(20)
        .all()
    )
    return render_template(
        "admin/pos_terminal.html",
        idempotency_key=secrets.token_urlsafe(32),
        payment_methods=POS_MVP_PAYMENT_METHOD_LABELS,
        selected_order=selected_order,
        order_number=order_number,
        transaction_limit=current_app.config.get("POS_MVP_TRANSACTION_LIMIT", 100000),
        recent_transactions=recent_transactions,
    )


def _pos_transaction_or_404(transaction_id):
    transaction = db.get_or_404(PosPaymentTransaction, transaction_id)
    abort_if_no_branch_access(transaction.branch_id, include_unassigned=True)
    return transaction


@admin_bp.route("/pos/transactions/<int:transaction_id>")
@admin_required
@operations_required
def pos_terminal_success(transaction_id):
    return render_template(
        "admin/pos_terminal_success.html",
        transaction=_pos_transaction_or_404(transaction_id),
    )


@admin_bp.route("/pos/transactions/<int:transaction_id>/receipt")
@admin_required
@operations_required
def pos_terminal_receipt(transaction_id):
    return render_template(
        "admin/pos_terminal_receipt.html",
        transaction=_pos_transaction_or_404(transaction_id),
    )


@admin_bp.route("/walk-in-orders", methods=["GET", "POST"])
@admin_bp.route("/pos", methods=["GET", "POST"])
@admin_required
@operations_required
def pos():
    variants = (
        scoped_variant_query(ProductVariant.query.join(Product))
        .filter(Product.is_active.is_(True))
        .order_by(Product.name.asc())
        .all()
    )
    if request.method == "POST":
        import json
        import uuid

        raw_items = request.form.get("cart_items") or ""
        sale_items = []
        if raw_items:
            try:
                decoded_items = json.loads(raw_items)
            except (TypeError, ValueError):
                decoded_items = []
            for item in decoded_items if isinstance(decoded_items, list) else []:
                try:
                    variant_id = int(item.get("variant_id"))
                    quantity = max(1, int(item.get("quantity") or 1))
                except (TypeError, ValueError, AttributeError):
                    continue
                sale_items.append({"variant_id": variant_id, "quantity": quantity})
        if not sale_items:
            variant_id = request.form.get("variant_id", type=int)
            quantity = max(1, request.form.get("quantity", type=int) or 1)
            if variant_id:
                sale_items.append({"variant_id": variant_id, "quantity": quantity})

        payment_mode = (request.form.get("payment_mode") or "CASH").strip().upper()
        if payment_mode not in {"CASH", "CARD", "UPI", "SWIGGY", "ZOMATO", "OTHER"}:
            payment_mode = "CASH"
        gst_order_source = (
            request.form.get("gst_order_source") or GST_ORDER_SOURCE_COUNTER_TAKEAWAY
        ).strip().upper()
        if payment_mode == "SWIGGY":
            gst_order_source = GST_ORDER_SOURCE_ECOMMERCE_SWIGGY
        elif payment_mode == "ZOMATO":
            gst_order_source = GST_ORDER_SOURCE_ECOMMERCE_ZOMATO
        if gst_order_source not in GST_ORDER_SOURCE_VALUES:
            gst_order_source = GST_ORDER_SOURCE_COUNTER_TAKEAWAY
        sale_status = (request.form.get("sale_status") or "DELIVERED").strip().upper()
        if sale_status not in {"DELIVERED", "PREPARING", "READY_FOR_PICKUP"}:
            sale_status = "DELIVERED"
        initial_status = "PLACED" if sale_status == "DELIVERED" else sale_status
        customer_name = (request.form.get("customer_name") or "").strip()
        customer_phone = (request.form.get("customer_phone") or "").strip()
        expected_versions = {}
        for variant in variants:
            expected_versions[str(variant.id)] = request.form.get(
                f"expected_version_{variant.id}"
            )
        order = None
        stock_update_variant_ids = []
        stock_update_material_ids = []
        try:
            customer = None
            if customer_phone:
                customer = User.query.filter_by(
                    phone=customer_phone,
                    role="customer",
                    is_active=True,
                ).first()
            with db.session.begin_nested():
                if customer is None:
                    guest_token = uuid.uuid4().hex[:10]
                    customer = User(
                        name=customer_name or "Walk-in Customer",
                        email=f"walkin-{guest_token}@sweetcrumbs.local",
                        role="customer",
                        is_active=True,
                        phone=customer_phone or None,
                    )
                    db.session.add(customer)
                    db.session.flush()

                order_service = get_container().order_service
                lines = []
                subtotal = Decimal("0")
                for item in sale_items:
                    variant = db.session.get(ProductVariant, item["variant_id"])
                    if variant is not None:
                        abort_if_no_branch_access(
                            variant.branch_id,
                            include_unassigned=True,
                        )
                    line = order_service.build_line_from_variant(
                        variant,
                        item["quantity"],
                    )
                    lines.append(line)
                    subtotal += line.unit_price * line.quantity

                finance_service = get_container().finance_service
                gst_rate = finance_service.resolve_active_sales_tax_rate()
                gst_payload = finance_service.sales_gst_context(
                    subtotal,
                    rate_percent=gst_rate,
                    gst_order_source=gst_order_source,
                    channel="counter",
                    source=payment_mode if payment_mode in {"SWIGGY", "ZOMATO"} else "POS",
                    fulfillment_type="PICKUP",
                )
                total = (subtotal + gst_payload["gst_amount"]).quantize(
                    Decimal("0.01")
                )
                store_details = current_app.config["STORE_DETAILS"]
                creation = order_service.create_order(
                    user_id=customer.id,
                    branch_id=(
                        current_admin_branch_id()
                        if current_admin_branch_id() is not None
                        else current_app.config.get("DEFAULT_BRANCH_ID")
                    ),
                    lines=lines,
                    subtotal=subtotal,
                    total=total,
                    payment_method=payment_mode,
                    payment_status="PENDING",
                    status=initial_status,
                    channel="counter",
                    source=payment_mode if payment_mode in {"SWIGGY", "ZOMATO"} else "POS",
                    fulfillment_type="PICKUP",
                    gst_rate=gst_rate,
                    gst_amount=gst_payload["gst_amount"],
                    gst_taxable_amount=gst_payload["taxable_amount"],
                    cgst_amount=gst_payload["cgst_amount"],
                    sgst_amount=gst_payload["sgst_amount"],
                    gst_supply_type=gst_payload["gst_supply_type"],
                    gst_order_source=gst_payload["gst_order_source"],
                    gst_liability_party=gst_payload["gst_liability_party"],
                    gst_return_bucket=gst_payload["gst_return_bucket"],
                    gst_invoice_note=gst_payload["gst_invoice_note"],
                    ecommerce_operator=gst_payload["ecommerce_operator"],
                    ecommerce_tcs_amount=gst_payload["ecommerce_tcs_amount"],
                    address_line1=store_details.get("address_line1", ""),
                    address_line2=store_details.get("address_line2", ""),
                    city=store_details.get("city", ""),
                    pincode=store_details.get("pincode", ""),
                    phone=customer_phone or store_details.get("phone_tel", ""),
                    delivery_slot="Walk-in",
                    delivery_date=utcnow().date(),
                    special_note=(request.form.get("special_note") or "").strip()
                    or None,
                    actor_id=current_user.id,
                    payment_reason="pos_sale",
                    expected_versions=expected_versions,
                )
                order = creation.order
                creation.payment.gateway_name = "manual_phone"
                creation.payment.gateway_payload = json.dumps(
                    {
                        "provider": "manual_phone",
                        "source": "manual_pos_terminal",
                        "intended_order_status": sale_status,
                        "amount_due": str(total),
                        "base_taxable_value": str(gst_payload["taxable_amount"]),
                        "cgst_amount": str(gst_payload["cgst_amount"]),
                        "sgst_amount": str(gst_payload["sgst_amount"]),
                        "gst_amount": str(gst_payload["gst_amount"]),
                        "gst_liability_party": gst_payload["gst_liability_party"],
                        "gst_return_bucket": gst_payload["gst_return_bucket"],
                    },
                    sort_keys=True,
                )
                stock_update_variant_ids = creation.stock_update_variant_ids
                stock_update_material_ids = creation.stock_update_material_ids
                get_container().audit_service.log(
                    current_user.id,
                    "pos_sale_created",
                    "Order",
                    order.id,
                    before=None,
                    after={
                        "order_number": order.order_number,
                        "channel": order.channel,
                        "line_count": len(lines),
                        "payment_mode": payment_mode,
                        "payment_status": "PENDING",
                        "intended_order_status": sale_status,
                        "gst_order_source": gst_payload["gst_order_source"],
                        "gst_amount": str(gst_payload["gst_amount"]),
                        "total": str(total),
                    },
                    branch_id=order.branch_id,
                    change_summary=(
                        f"Counter bill created for order #{order.order_number}; "
                        "awaiting POS payment."
                    ),
                )
            db.session.commit()
            emit_new_order(order)
            for variant_id in set(stock_update_variant_ids):
                variant = db.session.get(ProductVariant, variant_id)
                if variant:
                    emit_stock_updated(variant, include_customer=True)
            for material_id in set(stock_update_material_ids):
                material = db.session.get(RawMaterial, material_id)
                if material:
                    emit_stock_updated(material)
            flash(
                f"Walk-in bill #{order.order_number} created. Collect payment to generate the bill.",
                "success",
            )
            return redirect(url_for("admin.pos_payment", order_id=order.id))
        except ValidationError as exc:
            db.session.rollback()
            flash(str(exc), "danger")
        except SQLAlchemyError:
            db.session.rollback()
            if len(sale_items) == 1:
                request_id = get_container().offline_sync_service.queue_pos_sale(
                    variant_id=sale_items[0]["variant_id"],
                    quantity=sale_items[0]["quantity"],
                    payment_mode=payment_mode,
                    customer_phone=customer_phone,
                    actor_id=current_user.id,
                )
                flash(
                    f"Connection lost. POS sale queued locally for sync ({request_id[:8]}).",
                    "warning",
                )
            else:
                flash("Connection lost. Please retry this counter sale.", "danger")
        return redirect(url_for("admin.pos"))
    return render_template(
        "admin/pos.html",
        variants=variants,
        gst_rate=get_container().finance_service.resolve_active_sales_tax_rate(),
        gst_order_source_choices=GST_ORDER_SOURCE_CHOICES,
        default_gst_order_source=GST_ORDER_SOURCE_COUNTER_TAKEAWAY,
        can_update_walkin_availability=(
            not is_order_screen_user(current_user)
            and admin_tier_meets(current_user, "staff", "manager", "owner")
        ),
    )


def _counter_order_or_404(order_id):
    order = scoped_order_or_404(order_id, include_unassigned=True)
    if (order.channel or "").lower() != "counter":
        abort(404)
    return order


def _counter_payment_payload(order):
    import json

    payment = order.payment
    if payment is None or not payment.gateway_payload:
        return {}
    try:
        payload = json.loads(payment.gateway_payload)
    except (TypeError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


@admin_bp.route("/pos/orders/<int:order_id>/payment", methods=["GET", "POST"])
@admin_required
@operations_required
def pos_payment(order_id):
    order = _counter_order_or_404(order_id)
    if (order.payment_status or "").upper() == "PAID":
        return redirect(url_for("admin.pos_receipt", order_id=order.id))
    if (order.status or "").upper() in {"CANCELLED", "REFUNDED"}:
        flash("This walk-in bill has been voided.", "warning")
        return redirect(url_for("admin.pos"))

    payload = _counter_payment_payload(order)
    intended_status = (
        request.form.get("final_status")
        or payload.get("intended_order_status")
        or "DELIVERED"
    )
    intended_status = (intended_status or "DELIVERED").strip().upper()
    if intended_status not in {"DELIVERED", "PREPARING", "READY_FOR_PICKUP", "PLACED"}:
        intended_status = "DELIVERED"

    if request.method == "POST":
        try:
            result = get_container().payment_service.confirm_counter_payment(
                order,
                amount_received=request.form.get("amount_received"),
                payment_method=request.form.get("payment_method"),
                actor_id=current_user.id,
                provider="manual_phone",
                transaction_reference=request.form.get("payment_reference"),
                final_status=intended_status,
            )
            get_container().audit_service.log(
                current_user.id,
                "pos_payment_received",
                "Payment",
                result["payment"].id,
                before={"payment_status": "PENDING"},
                after={
                    "order_number": order.order_number,
                    "payment_method": order.payment_method,
                    "payment_status": order.payment_status,
                    "order_status": order.status,
                    "change_due": str(result["change_due"]),
                },
                branch_id=order.branch_id,
                change_summary=f"Manual POS payment received for #{order.order_number}.",
            )
            db.session.commit()
            rooms = ["admin", "kds", customer_room(order.user_id)]
            emit_order_status_updated(order, rooms)
            flash(
                f"Payment received for #{order.order_number}. Bill is ready.",
                "success",
            )
            return redirect(url_for("admin.pos_receipt", order_id=order.id))
        except ValidationError as exc:
            db.session.rollback()
            flash(str(exc), "danger")
        except SQLAlchemyError:
            db.session.rollback()
            flash("Unable to reconcile this POS payment right now.", "danger")

    return render_template(
        "admin/pos_payment.html",
        order=order,
        items=order.items.all(),
        intended_status=intended_status,
    )


@admin_bp.route("/pos/orders/<int:order_id>/receipt")
@admin_required
@operations_required
def pos_receipt(order_id):
    import io

    from services.invoice_service import InvoiceService

    order = _counter_order_or_404(order_id)
    if (order.payment_status or "").upper() != "PAID":
        flash("Collect payment before generating the bill/receipt.", "warning")
        return redirect(url_for("admin.pos_payment", order_id=order.id))
    try:
        pdf_bytes = InvoiceService(storage_service=None).generate_pdf_bytes(order)
        return send_file(
            io.BytesIO(pdf_bytes),
            mimetype="application/pdf",
            as_attachment=False,
            download_name=f"receipt-{order.order_number}.pdf",
        )
    except ModuleNotFoundError:
        current_app.logger.warning(
            "receipt_pdf_dependency_missing order_id=%s", order.id
        )
    return render_template(
        "admin/pos_receipt.html",
        order=order,
        items=order.items.all(),
        payment_payload=_counter_payment_payload(order),
    )


@admin_bp.route("/pos/orders/<int:order_id>/void", methods=["POST"])
@admin_required
@manager_required
def void_pos_bill(order_id):
    order = _counter_order_or_404(order_id)
    if (order.payment_status or "").upper() == "PAID":
        flash("Paid walk-in bills cannot be deleted. Use the refund workflow.", "warning")
        return redirect(url_for("admin.pos_receipt", order_id=order.id))

    reason = (
        request.form.get("reason") or "Pending walk-in bill voided by admin"
    ).strip()
    try:
        result = get_container().order_reversal_service.cancel_or_refund_order(
            order,
            reason=reason,
            actor_id=current_user.id,
            reverse_stock=True,
            allow_paid_refund=False,
            initiated_by="admin_pos_void",
        )
        db.session.commit()
        emit_order_cancelled(order, reason=reason)
        for variant_id in set(result.get("restored_variant_ids", [])):
            variant = db.session.get(ProductVariant, variant_id)
            if variant:
                emit_stock_updated(variant, include_customer=True)
        for movement in result.get("stock_movements", []):
            if movement.raw_material:
                emit_stock_updated(movement.raw_material)
        flash(f"Pending walk-in bill #{order.order_number} was voided.", "success")
    except ValidationError as exc:
        db.session.rollback()
        flash(str(exc), "danger")
    except SQLAlchemyError:
        db.session.rollback()
        flash("Unable to void this walk-in bill right now.", "danger")
    return redirect(url_for("admin.pos"))


@admin_bp.route("/pricing", methods=["GET", "POST"])
@admin_required
@manager_required
def pricing():
    if request.method == "POST":
        percent_discount = request.form.get("percent_discount", type=float) or 0
        rule = PricingRule(
            name=(request.form.get("name") or "Dynamic pricing rule").strip(),
            rule_type=(request.form.get("rule_type") or "scheduled_discount").strip(),
            category_id=request.form.get("category_id", type=int),
            branch_id=request.form.get("branch_id", type=int),
            percent_discount=percent_discount,
            applies_after_hour=request.form.get("applies_after_hour", type=int),
            max_batch_age_hours=request.form.get("max_batch_age_hours", type=int),
        )
        db.session.add(rule)
        db.session.flush()
        get_container().audit_service.log(
            current_user,
            "pricing_rule_created",
            "PricingRule",
            rule.id,
            after={
                "name": rule.name,
                "rule_type": rule.rule_type,
                "percent_discount": float(rule.percent_discount or 0),
            },
            branch_id=rule.branch_id,
            change_summary=f"Pricing rule created: {rule.name}",
        )
        db.session.commit()
        flash("Pricing rule saved.", "success")
        return redirect(url_for("admin.pricing"))
    rules = PricingRule.query.order_by(PricingRule.created_at.desc()).all()
    categories = Category.query.order_by(Category.name.asc()).all()
    branches = Branch.query.order_by(Branch.name.asc()).all()
    ai_offer_context = (
        get_container().offer_recommendation_service.build_pricing_ai_context()
    )
    return render_template(
        "admin/pricing.html",
        rules=rules,
        categories=categories,
        branches=branches,
        ai_offer_context=ai_offer_context,
    )


@admin_bp.route("/subscriptions")
@admin_required
@manager_required
def subscriptions_admin():
    memberships = Subscription.query.order_by(Subscription.start_date.desc()).all()
    recurring_subscriptions = RecurringSubscription.query.order_by(
        RecurringSubscription.next_scheduled_date.asc(),
        RecurringSubscription.created_at.desc(),
    ).all()
    failed_logs = (
        SubscriptionOrderLog.query.filter(
            SubscriptionOrderLog.status != "success",
        )
        .order_by(SubscriptionOrderLog.attempted_at.desc())
        .limit(50)
        .all()
    )
    schedules = SubscriptionSchedule.query.order_by(
        SubscriptionSchedule.next_run_at.asc()
    ).all()
    return render_template(
        "admin/subscriptions.html",
        memberships=memberships,
        recurring_subscriptions=recurring_subscriptions,
        failed_logs=failed_logs,
        schedules=schedules,
    )


@admin_bp.route("/corporate")
@admin_required
@manager_required
def corporate_dashboard():
    status = (request.args.get("status") or "").strip().lower()
    query = CorporateInquiry.query
    if status:
        query = query.filter(CorporateInquiry.status == status)
    inquiries = query.order_by(
        CorporateInquiry.created_at.desc(),
        CorporateInquiry.id.desc(),
    ).all()
    quotes = CorporateQuote.query.order_by(CorporateQuote.created_at.desc()).limit(25).all()
    return render_template(
        "admin/corporate.html",
        inquiries=inquiries,
        quotes=quotes,
        selected_status=status,
        statuses=[
            "new",
            "contacted",
            "requirements_confirmed",
            "quote_prepared",
            "quote_sent",
            "negotiation",
            "approved",
            "order_created",
            "completed",
            "rejected",
            "cancelled",
            "no_response",
            "expired",
        ],
    )


@admin_bp.route("/corporate/<int:inquiry_id>")
@admin_required
@manager_required
def corporate_inquiry_detail(inquiry_id):
    inquiry = db.get_or_404(CorporateInquiry, inquiry_id)
    return render_template(
        "admin/corporate_detail.html",
        inquiry=inquiry,
        quotes=inquiry.quotes.order_by(CorporateQuote.version.desc()).all(),
        status_events=inquiry.status_history.order_by(
            CorporateInquiryStatusHistory.created_at.desc()
        ).all(),
        statuses=[
            "new",
            "contacted",
            "requirements_confirmed",
            "quote_prepared",
            "quote_sent",
            "negotiation",
            "approved",
            "order_created",
            "completed",
            "rejected",
            "cancelled",
            "no_response",
            "expired",
        ],
    )


@admin_bp.route("/corporate/<int:inquiry_id>/status", methods=["POST"])
@admin_required
@manager_required
def update_corporate_inquiry_status(inquiry_id):
    inquiry = db.get_or_404(CorporateInquiry, inquiry_id)
    old_status = inquiry.status
    new_status = (request.form.get("status") or "").strip().lower()
    allowed = {
        "new",
        "contacted",
        "requirements_confirmed",
        "quote_prepared",
        "quote_sent",
        "negotiation",
        "approved",
        "order_created",
        "completed",
        "rejected",
        "cancelled",
        "no_response",
        "expired",
    }
    if new_status not in allowed:
        flash("Choose a valid corporate inquiry status.", "danger")
        return redirect(url_for("admin.corporate_inquiry_detail", inquiry_id=inquiry.id))
    inquiry.status = new_status
    inquiry.owner_id = request.form.get("owner_id", type=int) or inquiry.owner_id or current_user.id
    inquiry.follow_up_date = None
    follow_up_raw = (request.form.get("follow_up_date") or "").strip()
    if follow_up_raw:
        try:
            inquiry.follow_up_date = datetime.strptime(follow_up_raw, "%Y-%m-%d").date()
        except ValueError:
            flash("Follow-up date was invalid and was ignored.", "warning")
    inquiry.customer_visible_note = (request.form.get("customer_visible_note") or "").strip() or None
    inquiry.internal_notes = (request.form.get("internal_note") or "").strip() or inquiry.internal_notes
    db.session.add(
        CorporateInquiryStatusHistory(
            inquiry_id=inquiry.id,
            previous_status=old_status,
            new_status=new_status,
            updated_by=current_user.id,
            customer_visible_note=inquiry.customer_visible_note,
            internal_note=(request.form.get("internal_note") or "").strip() or None,
        )
    )
    get_container().audit_service.log(
        current_user,
        "corporate_inquiry_status_changed",
        "CorporateInquiry",
        inquiry.id,
        before={"status": old_status},
        after={"status": new_status},
        change_summary=f"Corporate inquiry status changed to {new_status}.",
    )
    db.session.commit()
    flash("Corporate inquiry updated.", "success")
    return redirect(url_for("admin.corporate_inquiry_detail", inquiry_id=inquiry.id))


@admin_bp.route("/corporate/<int:inquiry_id>/quotes", methods=["POST"])
@admin_required
@manager_required
def create_corporate_quote(inquiry_id):
    inquiry = db.get_or_404(CorporateInquiry, inquiry_id)
    latest = inquiry.quotes.order_by(CorporateQuote.version.desc()).first()
    subtotal = Decimal(str(request.form.get("subtotal") or 0))
    customization = Decimal(str(request.form.get("customization_charges") or 0))
    packaging = Decimal(str(request.form.get("packaging_charges") or 0))
    delivery = Decimal(str(request.form.get("delivery_charges") or 0))
    discount = Decimal(str(request.form.get("discount") or 0))
    tax = Decimal(str(request.form.get("tax_amount") or 0))
    total = (subtotal + customization + packaging + delivery - discount + tax).quantize(Decimal("0.01"))
    quote = CorporateQuote(
        inquiry_id=inquiry.id,
        version=(latest.version + 1) if latest else 1,
        status=(request.form.get("status") or "draft").strip().lower(),
        line_items_json=request.form.get("line_items_json") or "[]",
        subtotal=subtotal,
        customization_charges=customization,
        packaging_charges=packaging,
        delivery_charges=delivery,
        discount=discount,
        tax_amount=tax,
        total=total,
        advance_required=Decimal(str(request.form.get("advance_required") or 0)),
        payment_terms=(request.form.get("payment_terms") or "").strip() or None,
        delivery_schedule=(request.form.get("delivery_schedule") or "").strip() or None,
        terms=(request.form.get("terms") or "").strip() or None,
        created_by=current_user.id,
    )
    validity_raw = (request.form.get("validity_date") or "").strip()
    if validity_raw:
        try:
            quote.validity_date = datetime.strptime(validity_raw, "%Y-%m-%d").date()
        except ValueError:
            pass
    inquiry.status = "quote_prepared"
    db.session.add(quote)
    db.session.flush()
    get_container().audit_service.log(
        current_user,
        "corporate_quote_created",
        "CorporateQuote",
        quote.id,
        after={"inquiry_id": inquiry.id, "total": float(total)},
        change_summary=f"Corporate quote v{quote.version} prepared.",
    )
    db.session.commit()
    flash("Corporate quote saved.", "success")
    return redirect(url_for("admin.corporate_inquiry_detail", inquiry_id=inquiry.id))


@admin_bp.route("/audit")
@admin_bp.route("/audit-log")
@admin_required
@owner_required
def audit():
    audit_service = get_container().audit_service
    actor_id = request.args.get("actor_id", type=int)
    action = (request.args.get("action") or "").strip() or None
    start_date = request.args.get("start_date") or None
    end_date = request.args.get("end_date") or None
    logs = audit_service.query_logs(
        actor_id=actor_id,
        action=action,
        start_date=start_date,
        end_date=end_date,
        limit=250,
    )
    actors = (
        User.query.filter(
            User.role.in_(
                (
                    "admin",
                    "super_admin",
                    "branch_manager",
                    "cashier",
                    "kitchen_staff",
                    "delivery",
                )
            )
        )
        .order_by(User.name.asc())
        .all()
    )
    actions = audit_service.distinct_actions()
    alerts = (
        OperationalAlert.query.order_by(OperationalAlert.created_at.desc())
        .limit(20)
        .all()
    )
    fraud_alerts = (
        FraudAlert.query.order_by(FraudAlert.created_at.desc()).limit(20).all()
    )
    return render_template(
        "admin/audit.html",
        logs=logs,
        actors=actors,
        actions=actions,
        selected_actor_id=actor_id,
        selected_action=action or "",
        start_date=start_date or "",
        end_date=end_date or "",
        alerts=alerts,
        fraud_alerts=fraud_alerts,
    )


@admin_bp.route("/queue-monitor")
@admin_required
@manager_required
def queue_monitor():
    offline_sync = get_container().offline_sync_service
    pending_actions = (
        offline_sync.pending_actions(limit=100) if offline_sync.enabled else []
    )
    db.session.add(
        QueueMetric(
            queue_name="offline_sync",
            backlog=len(pending_actions),
            failed_count=0,
            retry_count=len(
                [item for item in pending_actions if item.get("status") == "retry"]
            ),
        )
    )
    db.session.commit()
    recent_metrics = (
        QueueMetric.query.order_by(QueueMetric.recorded_at.desc()).limit(20).all()
    )
    api_usage = (
        ApiUsageLog.query.order_by(ApiUsageLog.created_at.desc()).limit(20).all()
    )
    celery_summary = {"registered_tasks": 0, "active_workers": 0}
    try:
        from models import celery as celery_app

        inspector = celery_app.control.inspect(timeout=1.0)
        if inspector:
            registered = inspector.registered() or {}
            active = inspector.active() or {}
            celery_summary = {
                "registered_tasks": sum(len(tasks) for tasks in registered.values()),
                "active_workers": len(active),
            }
    except Exception:
        pass
    return render_template(
        "admin/queue_monitor.html",
        pending_actions=pending_actions,
        recent_metrics=recent_metrics,
        api_usage=api_usage,
        celery_summary=celery_summary,
    )


@admin_bp.route("/offline")
@admin_required
@manager_required
def offline_admin():
    offline_sync = get_container().offline_sync_service
    conflicts = (
        SyncConflict.query.filter(SyncConflict.resolved_at.is_(None))
        .order_by(SyncConflict.created_at.desc())
        .limit(50)
        .all()
    )
    pending_actions = (
        offline_sync.pending_actions(limit=50) if offline_sync.enabled else []
    )
    return render_template(
        "admin/offline.html",
        conflicts=conflicts,
        pending_actions=pending_actions,
        online=offline_sync.is_online() if offline_sync.enabled else True,
    )


@admin_bp.route("/offline/conflicts/<int:conflict_id>/resolve", methods=["POST"])
@admin_required
@manager_required
def resolve_sync_conflict(conflict_id):
    resolution = (request.form.get("resolution") or "accept_local").strip().lower()
    try:
        get_container().offline_sync_service.resolve_conflict(
            conflict_id,
            resolution,
            actor_id=current_user.id,
        )
        flash("Sync conflict resolved.", "success")
    except ValidationError as exc:
        flash(str(exc), "danger")
    return redirect(url_for("admin.offline_admin"))


@admin_bp.route("/delivery/routes/plan", methods=["POST"])
@admin_required
@manager_required
def plan_delivery_routes():
    agent_id = request.form.get("agent_id", type=int)
    agent = db.get_or_404(DeliveryAgent, agent_id)
    deliveries = (
        Delivery.query.filter_by(agent_id=agent_id)
        .filter(Delivery.status.in_(["ASSIGNED", "OUT_FOR_DELIVERY"]))
        .all()
    )
    plan = get_container().route_planning_service.plan_for_agent(agent, deliveries)
    flash(
        f"Route planned with {plan.stop_count} stops (~{plan.estimated_duration_minutes} min).",
        "success",
    )
    return redirect(url_for("admin.orders"))


@admin_bp.route("/qr-scanner")
@admin_required
@operations_required
def qr_scanner():
    return render_template("admin/qr_scanner.html")


def _finance_request_period():
    period = (
        request.args.get("period")
        or request.form.get("period")
        or (
            "custom"
            if (request.args.get("start_date") or request.form.get("start_date"))
            else "month"
        )
    )
    today = utcnow().date()
    default_start = today.replace(day=1)
    start_date = (
        request.args.get("start_date")
        or request.form.get("start_date")
        or default_start.isoformat()
    )
    end_date = (
        request.args.get("end_date")
        or request.form.get("end_date")
        or today.isoformat()
    )
    return period, start_date, end_date


def _finance_date_range():
    period, start_date, end_date = _finance_request_period()
    selected = get_container().finance_service.resolve_period_range(
        period,
        start_date=start_date,
        end_date=end_date,
    )
    start_date = selected["start_date"]
    end_date = selected["end_date"]
    return start_date, end_date


# ── FINANCE ──────────────────────────────────────────────────
@admin_bp.route("/finance")
@finance_required
def finance_dashboard():
    finance = get_container().finance_service
    finance.ensure_default_categories()
    period, start_date, end_date = _finance_request_period()
    payload = finance.dashboard_payload(
        period,
        start_date=start_date,
        end_date=end_date,
    )
    selected = payload["selected_period"]
    transactions = finance._transactions_in_period(selected["start"], selected["end"])[
        :25
    ]
    return render_template(
        "admin/finance/dashboard.html",
        dashboard=payload,
        selected_period=selected,
        pnl=payload["pnl"],
        gst=payload["gst"],
        transactions=transactions,
        start_date=selected["start_date"],
        end_date=selected["end_date"],
        period=selected["period"],
    )


@admin_bp.route("/finance/consistency-check", methods=["POST"])
@finance_required
def finance_consistency_check():
    finance = get_container().finance_service
    period, start_date, end_date = _finance_request_period()
    selected = finance.resolve_period_range(
        period, start_date=start_date, end_date=end_date
    )
    check = finance.revenue_consistency_check(
        start_date=selected["start_date"],
        end_date=selected["end_date"],
    )
    if check["matches"]:
        flash(
            "Revenue consistency check passed: order sales and finance ledger sales agree.",
            "success",
        )
    else:
        flash(
            (
                "Revenue consistency warning: orders show "
                f"₹{int(check['order_revenue'])}, ledger shows ₹{int(check['ledger_revenue'])}, "
                f"difference ₹{int(check['difference'])}; missing ledger orders: {check['missing_count']}."
            ),
            "warning",
        )
    return redirect(
        url_for(
            "admin.finance_dashboard",
            period=selected["period"],
            start_date=selected["start_date"],
            end_date=selected["end_date"],
        )
    )


@admin_bp.route("/finance/transactions/add", methods=["GET", "POST"])
@finance_required
def finance_add_transaction():
    finance = get_container().finance_service
    finance.ensure_default_categories()
    categories = finance.active_categories()
    if request.method == "POST":
        try:
            amount = parse_decimal(request.form.get("amount"), "amount")
            tax_amount_raw = (request.form.get("tax_amount") or "").strip()
            tax_amount = (
                parse_decimal(tax_amount_raw, "tax amount") if tax_amount_raw else None
            )
            tds_raw = (request.form.get("tds_withheld") or "").strip()
            tds_withheld = parse_decimal(tds_raw, "TDS withheld") if tds_raw else None
        except ValueError as exc:
            flash(str(exc), "danger")
            return redirect(url_for("admin.finance_add_transaction"))

        category_id = request.form.get("category_id", type=int)
        category = db.session.get(FinancialCategory, category_id)
        if category is None:
            flash("Choose a valid category.", "danger")
            return redirect(url_for("admin.finance_add_transaction"))

        finance.create_manual_transaction(
            transaction_type=request.form.get("transaction_type")
            or category.transaction_type,
            category_id=category.id,
            amount=amount,
            tax_amount=tax_amount,
            description=request.form.get("description", ""),
            counterparty=request.form.get("counterparty", ""),
            branch_id=request.form.get("branch_id", type=int),
            tds_withheld=tds_withheld,
            payment_method=normalize_vendor_payment_method(
                request.form.get("payment_method")
            ),
            vendor_id=request.form.get("vendor_id", type=int),
            created_by=current_user.id,
        )
        db.session.commit()
        flash("Financial transaction recorded.", "success")
        return redirect(url_for("admin.finance_dashboard"))

    branches = Branch.query.filter_by(is_active=True).order_by(Branch.name.asc()).all()
    vendors = Vendor.query.filter_by(is_active=True).order_by(Vendor.name.asc()).all()
    return render_template(
        "admin/finance/transaction_form.html",
        categories=categories,
        branches=branches,
        vendors=vendors,
        payment_method_choices=VENDOR_PAYMENT_METHOD_CHOICES,
    )


@admin_bp.route("/finance/ledger/products")
@finance_required
def finance_product_ledger():
    start_date, end_date = _finance_date_range()
    rows = get_container().finance_service.product_ledger(
        start_date=start_date, end_date=end_date
    )
    return render_template(
        "admin/finance/product_ledger.html",
        rows=rows,
        start_date=start_date,
        end_date=end_date,
    )


@admin_bp.route("/finance/ledger/stores")
@finance_required
def finance_store_ledger():
    start_date, end_date = _finance_date_range()
    rows = get_container().finance_service.store_ledger(
        start_date=start_date, end_date=end_date
    )
    return render_template(
        "admin/finance/store_ledger.html",
        rows=rows,
        start_date=start_date,
        end_date=end_date,
    )


@admin_bp.route("/finance/gst")
@finance_required
def finance_gst_summary():
    start_date, end_date = _finance_date_range()
    finance = get_container().finance_service
    summary = finance.gst_summary(start_date=start_date, end_date=end_date)
    records = TaxRecord.query.order_by(TaxRecord.computed_at.desc()).limit(12).all()
    return render_template(
        "admin/finance/gst_summary.html",
        summary=summary,
        records=records,
        start_date=start_date,
        end_date=end_date,
    )


@admin_bp.route("/finance/gst/snapshot", methods=["POST"])
@finance_required
def finance_gst_snapshot():
    start_date, end_date = _finance_date_range()
    period_type = (request.form.get("period_type") or "month").strip().lower()
    notes = request.form.get("admin_notes", "")
    get_container().finance_service.save_tax_record(
        period_type,
        start_date,
        end_date,
        admin_notes=notes,
    )
    db.session.commit()
    flash(
        "GST snapshot saved for review. Figures are not filed automatically.", "success"
    )
    return redirect(
        url_for("admin.finance_gst_summary", start_date=start_date, end_date=end_date)
    )


@admin_bp.route("/finance/tds")
@finance_required
def finance_tds_summary():
    start_date, end_date = _finance_date_range()
    summary = get_container().finance_service.tds_summary(
        start_date=start_date, end_date=end_date
    )
    return render_template(
        "admin/finance/tds_summary.html",
        summary=summary,
        start_date=start_date,
        end_date=end_date,
    )


@admin_bp.route("/finance/restock/<int:movement_id>", methods=["GET", "POST"])
@finance_required
def finance_log_restock(movement_id):
    movement = db.get_or_404(StockMovement, movement_id)
    finance = get_container().finance_service
    suggested = finance.suggest_restock_expense_amount(movement)
    if request.method == "POST":
        try:
            amount = parse_decimal(request.form.get("amount"), "amount")
            tax_raw = (request.form.get("tax_amount") or "").strip()
            tax_amount = parse_decimal(tax_raw, "tax amount") if tax_raw else None
        except ValueError as exc:
            flash(str(exc), "danger")
            return redirect(
                url_for("admin.finance_log_restock", movement_id=movement_id)
            )

        finance.log_restock_expense(
            movement,
            amount=amount,
            tax_amount=tax_amount,
            counterparty=request.form.get("counterparty", ""),
            created_by=current_user.id,
        )
        db.session.commit()
        flash("Restock expense logged.", "success")
        return redirect(url_for("admin.finance_dashboard"))

    return render_template(
        "admin/finance/log_restock.html",
        movement=movement,
        suggested_amount=suggested,
    )


@admin_bp.route("/finance/tax-rates")
@finance_required
def finance_tax_rates():
    rates = TaxRate.query.order_by(TaxRate.effective_from.desc()).all()
    return render_template("admin/finance/tax_rates.html", rates=rates)


@admin_bp.route("/finance/tax-rates/add", methods=["POST"])
@finance_required
def finance_add_tax_rate():
    try:
        rate_percent = parse_decimal(request.form.get("rate_percent"), "rate")
    except ValueError as exc:
        flash(str(exc), "danger")
        return redirect(url_for("admin.finance_tax_rates"))

    code = (request.form.get("code") or "").strip().lower().replace(" ", "_")
    if not code:
        flash("Tax rate code is required.", "danger")
        return redirect(url_for("admin.finance_tax_rates"))

    effective_from = request.form.get("effective_from") or utcnow().date().isoformat()
    db.session.add(
        TaxRate(
            name=(request.form.get("name") or code).strip(),
            code=code,
            rate_percent=rate_percent,
            applies_to=(request.form.get("applies_to") or "sales").strip(),
            effective_from=date.fromisoformat(effective_from),
            is_active=True,
            notes=(request.form.get("notes") or "").strip() or None,
        )
    )
    db.session.commit()
    flash("Tax rate added. Review applicability with your accountant.", "success")
    return redirect(url_for("admin.finance_tax_rates"))


@admin_bp.route("/finance/export/<report>/<file_format>")
@finance_required
def finance_export(report, file_format):
    import io

    period, requested_start, requested_end = _finance_request_period()
    finance = get_container().finance_service
    export = get_container().finance_export_service
    selected = finance.resolve_period_range(
        period,
        start_date=requested_start,
        end_date=requested_end,
    )
    start_date = selected["start_date"]
    end_date = selected["end_date"]
    file_format = (file_format or "csv").lower()
    report = (report or "pnl").lower()

    def send_export(content, mimetype, filename):
        return send_file(
            io.BytesIO(content),
            mimetype=mimetype,
            as_attachment=True,
            download_name=filename,
        )

    if report in {"dashboard", "summary"}:
        payload = finance.dashboard_payload(
            selected["period"], start_date=start_date, end_date=end_date
        )
        rows = [
            ["Period", payload["selected_period"]["label"]],
            ["Start", start_date],
            ["End", end_date],
            ["Sales Revenue", payload["pnl"]["sales_revenue"]],
            ["Other Income", payload["pnl"]["other_income"]],
            ["Total Income", payload["pnl"]["income"]],
            ["Expenses", payload["pnl"]["expenses"]],
            ["Net Profit", payload["pnl"]["net_profit"]],
            ["GST Collected", payload["gst"]["gst_collected"]],
            ["GST Paid by Aggregators", payload["gst"]["ecommerce_operator_gst"]],
            ["Supplier GST Recorded", payload["gst"]["input_gst_recorded"]],
            ["Blocked Input GST", payload["gst"]["non_creditable_input_gst"]],
            ["E-commerce TCS", payload["gst"]["ecommerce_tcs"]],
            ["Net GST Liability", payload["gst"]["net_gst_liability"]],
            [
                "Units Sold",
                sum(row["units_sold"] for row in payload["sales"]["units_sold"]),
            ],
            ["Revenue Consistency Difference", payload["consistency"]["difference"]],
        ]
        if file_format == "pdf":
            content = export.simple_pdf(
                "Unified Finance Dashboard",
                [f"{label}: {value}" for label, value in rows],
            )
            return send_export(
                content,
                "application/pdf",
                f"finance_dashboard_{start_date}_{end_date}.pdf",
            )
        return send_export(
            export.rows_csv(["Metric", "Value"], rows),
            "text/csv",
            f"finance_dashboard_{start_date}_{end_date}.csv",
        )
    if report == "pnl":
        payload = finance.profit_and_loss(start_date=start_date, end_date=end_date)
        if file_format == "pdf":
            content = export.profit_and_loss_pdf(payload)
            mimetype = "application/pdf"
            filename = f"pnl_{start_date}_{end_date}.pdf"
        else:
            content = export.rows_csv(
                ["Income", "Expenses", "Net Profit"],
                [[payload["income"], payload["expenses"], payload["net_profit"]]],
            )
            mimetype = "text/csv"
            filename = f"pnl_{start_date}_{end_date}.csv"
    elif report == "sales":
        payload = finance.dashboard_payload(
            selected["period"], start_date=start_date, end_date=end_date
        )["sales"]
        rows = [
            [
                row["product_name"],
                row["units_sold"],
                row["revenue"],
            ]
            for row in payload["units_sold"]
        ]
        if file_format == "pdf":
            lines = [
                f"Period: {start_date} to {end_date}",
                f"Revenue: INR {payload['revenue']}",
                f"Best by units: {(payload['top_sellers']['by_units'] or {}).get('product_name', 'None')}",
                "",
            ] + [
                f"{name}: units={units}, revenue={revenue}"
                for name, units, revenue in rows
            ]
            content = export.simple_pdf("Sales Performance", lines)
            mimetype = "application/pdf"
            filename = f"sales_{start_date}_{end_date}.pdf"
        else:
            content = export.rows_csv(["Product", "Units Sold", "Revenue"], rows)
            mimetype = "text/csv"
            filename = f"sales_{start_date}_{end_date}.csv"
    elif report == "categories":
        breakdown = finance.category_breakdown(start_date=start_date, end_date=end_date)
        rows = [
            [row["transaction_type"], row["category"], row["amount"]]
            for section in ("income", "expenses")
            for row in breakdown[section]
        ]
        if file_format == "pdf":
            content = export.simple_pdf(
                "Income and Expense Breakdown",
                [f"Period: {start_date} to {end_date}", ""]
                + [
                    f"{txn_type}: {category} INR {amount}"
                    for txn_type, category, amount in rows
                ],
            )
            mimetype = "application/pdf"
            filename = f"category_breakdown_{start_date}_{end_date}.pdf"
        else:
            content = export.rows_csv(["Type", "Category", "Amount"], rows)
            mimetype = "text/csv"
            filename = f"category_breakdown_{start_date}_{end_date}.csv"
    elif report == "products":
        rows = finance.product_ledger(start_date=start_date, end_date=end_date)
        if file_format == "pdf":
            start, end = (
                finance.profit_and_loss(start_date=start_date, end_date=end_date)[
                    "start"
                ],
                finance.profit_and_loss(start_date=start_date, end_date=end_date)[
                    "end"
                ],
            )
            content = export.product_ledger_pdf(rows, start, end)
            mimetype = "application/pdf"
            filename = f"product_ledger_{start_date}_{end_date}.pdf"
        else:
            content = export.rows_csv(
                ["Product", "Units Sold", "Revenue", "COGS", "Gross Profit"],
                [
                    [
                        r["product_name"],
                        r["units_sold"],
                        r["revenue"],
                        r["cogs"],
                        r["gross_profit"],
                    ]
                    for r in rows
                ],
            )
            mimetype = "text/csv"
            filename = f"product_ledger_{start_date}_{end_date}.csv"
    elif report == "stores":
        rows = finance.store_ledger(start_date=start_date, end_date=end_date)
        csv_rows = [[r["store"], r["income"], r["expenses"], r["net"]] for r in rows]
        if file_format == "pdf":
            content = export.simple_pdf(
                "Store P&L",
                [f"Period: {start_date} to {end_date}", ""]
                + [
                    f"{store}: income={income} expenses={expenses} net={net}"
                    for store, income, expenses, net in csv_rows
                ],
            )
            mimetype = "application/pdf"
            filename = f"store_ledger_{start_date}_{end_date}.pdf"
        else:
            content = export.rows_csv(["Store", "Income", "Expenses", "Net"], csv_rows)
            mimetype = "text/csv"
            filename = f"store_ledger_{start_date}_{end_date}.csv"
    elif report == "vendors":
        rows = finance.vendor_spend_report(start_date=start_date, end_date=end_date)
        csv_rows = [
            [
                row["vendor_name"],
                row["transaction_count"],
                row["total_spend"],
                row["gst_paid"],
                (
                    "eligible"
                    if row["input_tax_credit_eligible"]
                    else (
                        "blocked - 5% restaurant no ITC"
                        if row.get("input_tax_credit_blocked")
                        else "no gstin"
                    )
                ),
            ]
            for row in rows
        ]
        if file_format == "pdf":
            content = export.simple_pdf(
                "Vendor Spend",
                [f"Period: {start_date} to {end_date}", ""]
                + [
                    f"{vendor}: purchases={count} spend={spend} gst_paid={gst_paid} itc={itc}"
                    for vendor, count, spend, gst_paid, itc in csv_rows
                ],
            )
            mimetype = "application/pdf"
            filename = f"vendor_spend_{start_date}_{end_date}.pdf"
        else:
            content = export.rows_csv(
                ["Vendor", "Purchases", "Total Spend", "GST Paid", "ITC Treatment"],
                csv_rows,
            )
            mimetype = "text/csv"
            filename = f"vendor_spend_{start_date}_{end_date}.csv"
    elif report == "gst":
        payload = finance.gst_summary(start_date=start_date, end_date=end_date)
        if file_format == "pdf":
            content = export.gst_summary_pdf(payload)
            mimetype = "application/pdf"
            filename = f"gst_summary_{start_date}_{end_date}.pdf"
        else:
            rows = [
                [
                    row["order_date"] or "",
                    row["invoice_number"],
                    row["order_source"],
                    row["base_taxable_value"],
                    row["cgst_amount"],
                    row["sgst_amount"],
                    row["tax_liability_flag"],
                    row["gst_return_bucket"],
                    row["ecommerce_operator"],
                    row["ecommerce_tcs_amount"],
                ]
                for row in payload["rows"]
            ]
            content = export.rows_csv(
                [
                    "Order Date",
                    "Invoice Number",
                    "Order Source",
                    "Base Taxable Value",
                    "CGST (2.5%)",
                    "SGST (2.5%)",
                    "Tax Liability Flag",
                    "GSTR Bucket",
                    "E-commerce Operator",
                    "TCS (1%)",
                ],
                rows,
            )
            mimetype = "text/csv"
            filename = f"gst_summary_{start_date}_{end_date}.csv"
    elif report == "itr":
        payload = finance.finance_health_for_current_year()
        rows = [
            ["Financial Year", payload["label"]],
            ["Start", payload["start_date"]],
            ["End", payload["end_date"]],
            ["Total Income", payload["total_income"]],
            ["Total Expenses", payload["total_expenses"]],
            ["Net Income", payload["net_income"]],
            ["Tax Collected", payload["tax_collected"]],
            ["Tax Paid", payload["tax_paid"]],
            ["Net Tax Liability", payload["net_tax_liability"]],
        ]
        rows.extend(
            [
                ["Expense Category", row["category"], row["amount"]]
                for row in payload["expense_categories"]
            ]
        )
        if file_format == "pdf":
            content = export.simple_pdf(
                "Financial Health at a Glance",
                [": ".join(str(part) for part in row) for row in rows],
            )
            mimetype = "application/pdf"
            filename = f"financial_year_health_{payload['start_date']}_{payload['end_date']}.pdf"
        else:
            content = export.rows_csv(["Metric", "Value", "Amount"], rows)
            mimetype = "text/csv"
            filename = f"financial_year_health_{payload['start_date']}_{payload['end_date']}.csv"
    elif report == "transactions":
        txns = finance._transactions_in_period(selected["start"], selected["end"])
        if file_format == "pdf":
            lines = [f"Period: {start_date} to {end_date}", ""]
            lines.extend(
                f"{txn.created_at.date()}: {txn.transaction_type} {txn.category.label if txn.category else ''} INR {txn.amount}"
                for txn in txns
            )
            content = export.simple_pdf("Financial Transactions", lines)
            mimetype = "application/pdf"
            filename = f"transactions_{start_date}_{end_date}.pdf"
        else:
            content = export.transactions_csv(txns)
            mimetype = "text/csv"
            filename = f"transactions_{start_date}_{end_date}.csv"
    else:
        abort(404)

    return send_export(content, mimetype, filename)
