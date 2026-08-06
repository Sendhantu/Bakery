"""Permission catalog for the employee RBAC system.

Every permission is a `module.action` key. Roles, individual employee
overrides, temporary permissions and approval workflows all reference these
keys. Sensitive permissions (profit, refunds, customer deletion, tax settings,
inventory adjustment, gift-card balance adjustment, role management, ...)
require a reason when granted and trigger confirmation warnings in the UI.
"""

# module -> ordered list of (permission_key, label)
PERMISSION_SPECS = {
    "dashboard": [
        ("dashboard.view", "View dashboard"),
        ("dashboard.view_sales_summary", "View sales summary"),
        ("dashboard.view_profit", "View profit information"),
        ("dashboard.view_branch_performance", "View branch performance"),
    ],
    "orders": [
        ("orders.view", "View orders"),
        ("orders.create", "Create orders"),
        ("orders.update_status", "Update order status"),
        ("orders.cancel", "Cancel orders"),
        ("orders.approve_cancellations", "Approve cancellations"),
        ("orders.process_refunds", "Process refunds"),
        ("orders.view_customer_details", "View customer details"),
        ("orders.export", "Export orders"),
    ],
    "products": [
        ("products.view", "View products"),
        ("products.create", "Add products"),
        ("products.edit", "Edit products"),
        ("products.delete", "Delete products"),
        ("products.change_prices", "Change prices"),
        ("products.update_stock", "Update stock availability"),
        ("products.publish", "Publish or unpublish products"),
    ],
    "raw_materials": [
        ("raw_materials.view", "View raw materials"),
        ("raw_materials.create", "Add raw materials"),
        ("raw_materials.edit", "Edit material details"),
        ("raw_materials.add_stock", "Add stock"),
        ("raw_materials.record_usage", "Record usage"),
        ("raw_materials.record_wastage", "Record wastage"),
        ("raw_materials.record_damage", "Record damage"),
        ("raw_materials.adjust_stock", "Adjust stock"),
        ("raw_materials.view_purchase_history", "View purchase history"),
        ("raw_materials.record_supplier_payments", "Record supplier payments"),
        ("raw_materials.delete", "Delete eligible records"),
        ("raw_materials.export", "Export inventory"),
    ],
    "customers": [
        ("customers.view", "View customers"),
        ("customers.edit", "Edit customer details"),
        ("customers.view_contact_info", "View customer contact information"),
        ("customers.view_purchase_history", "View purchase history"),
        ("customers.view_occasions", "View customer occasions"),
        ("customers.view_vip", "View VIP customer information"),
        ("customers.send_promotional_messages", "Send promotional messages"),
        ("customers.send_gifts", "Send gifts"),
        ("customers.flag_suspicious", "Flag suspicious customers"),
        ("customers.suspend", "Suspend customers"),
        ("customers.restore", "Restore customers"),
        ("customers.delete", "Delete or anonymize customers"),
    ],
    "finance": [
        ("finance.view", "View finance dashboard"),
        ("finance.view_revenue", "View revenue"),
        ("finance.view_expenses", "View expenses"),
        ("finance.add_expenses", "Add expenses"),
        ("finance.edit_expenses", "Edit expenses"),
        ("finance.approve_expenses", "Approve expenses"),
        ("finance.view_transactions", "View payment transactions"),
        ("finance.view_profit", "View profit"),
        ("finance.export", "Export finance reports"),
    ],
    "tax": [
        ("tax.view_summary", "View tax summary"),
        ("tax.view_transactions", "View tax transactions"),
        ("tax.edit_settings", "Edit tax settings"),
        ("tax.export", "Export tax records"),
        ("tax.view_business_number", "View business tax number"),
    ],
    "gift_cards": [
        ("gift_cards.view", "View gift cards"),
        ("gift_cards.issue", "Issue gift cards"),
        ("gift_cards.collect_cash", "Collect cash"),
        ("gift_cards.redeem", "Redeem gift cards"),
        ("gift_cards.refund", "Refund gift cards"),
        ("gift_cards.cancel", "Cancel gift cards"),
        ("gift_cards.reissue", "Reissue gift cards"),
        ("gift_cards.adjust_balance", "Adjust gift-card balance"),
        ("gift_cards.export", "Export gift-card reports"),
    ],
    "suppliers": [
        ("suppliers.view", "View suppliers"),
        ("suppliers.create", "Add suppliers"),
        ("suppliers.edit", "Edit suppliers"),
        ("suppliers.create_purchase_orders", "Create purchase orders"),
        ("suppliers.approve_purchase_orders", "Approve purchase orders"),
        ("suppliers.record_received", "Record materials received"),
        ("suppliers.record_payments", "Record payments"),
        ("suppliers.view_payment_details", "View payment details"),
        ("suppliers.cancel_purchases", "Cancel purchases"),
    ],
    "employees": [
        ("employees.view", "View employees"),
        ("employees.create", "Add employees"),
        ("employees.edit", "Edit employees"),
        ("employees.assign_roles", "Assign roles"),
        ("employees.grant_permissions", "Grant permissions"),
        ("employees.suspend_access", "Suspend employee access"),
        ("employees.remove", "Remove employees"),
        ("employees.view_activity", "View employee activity"),
    ],
    "ai": [
        ("ai.use_assistant", "Use AI assistant"),
        ("ai.view_usage", "View AI usage"),
        ("ai.manage_settings", "Manage AI settings"),
        ("ai.view_customer_conversations", "View customer AI conversations"),
        ("ai.delete_history", "Delete eligible AI history"),
        ("ai.manage_recommendations", "Manage AI product recommendations"),
    ],
    "marketing": [
        ("marketing.view", "View campaigns"),
        ("marketing.create", "Create campaigns"),
        ("marketing.edit", "Edit campaigns"),
        ("marketing.approve", "Approve campaigns"),
        ("marketing.send_messages", "Send messages"),
        ("marketing.view_consent", "View customer consent"),
        ("marketing.export", "Export campaign results"),
    ],
    "reports": [
        ("reports.view", "View reports"),
        ("reports.export", "Export reports"),
        ("reports.view_sensitive", "View sensitive reports"),
        ("reports.schedule", "Schedule reports"),
    ],
    "settings": [
        ("settings.view", "View settings"),
        ("settings.edit_general", "Edit general settings"),
        ("settings.manage_delivery", "Manage delivery settings"),
        ("settings.manage_payment", "Manage payment settings"),
        ("settings.manage_tax", "Manage tax settings"),
        ("settings.manage_security", "Manage security settings"),
        ("settings.manage_roles", "Manage roles and permissions"),
    ],
}

MODULE_LABELS = {
    "dashboard": "Dashboard",
    "orders": "Orders",
    "products": "Products",
    "raw_materials": "Raw Materials",
    "customers": "Customers",
    "finance": "Finance",
    "tax": "Tax",
    "gift_cards": "Gift Cards",
    "suppliers": "Suppliers and Purchases",
    "employees": "Employees",
    "ai": "AI Management",
    "marketing": "Marketing",
    "reports": "Reports",
    "settings": "Settings",
}

# Field-level access keys (used to mask sensitive values in templates/routes).
FIELD_ACCESS_KEYS = {
    "customer_mobile": "customers.view_contact_info",
    "customer_email": "customers.view_contact_info",
    "customer_address": "customers.view_contact_info",
    "customer_dob": "customers.view_occasions",
    "customer_anniversary": "customers.view_occasions",
    "customer_risk_status": "customers.view_vip",
    "employee_salary": "employees.view_activity",
    "profit_margins": "finance.view_profit",
    "supplier_bank_details": "suppliers.view_payment_details",
    "tax_registration": "tax.view_business_number",
    "payment_references": "suppliers.view_payment_details",
    "gift_card_code": "gift_cards.view",
    "admin_notes": "employees.view_activity",
}

# Permissions that trigger a sensitive-access confirmation warning.
SENSITIVE_PERMISSIONS = frozenset(
    {
        "employees.assign_roles",
        "employees.grant_permissions",
        "employees.remove",
        "finance.view",
        "finance.view_profit",
        "orders.process_refunds",
        "customers.delete",
        "customers.view_contact_info",
        "tax.edit_settings",
        "raw_materials.adjust_stock",
        "gift_cards.adjust_balance",
        "settings.manage_payment",
        "settings.manage_tax",
        "settings.manage_security",
        "settings.manage_roles",
        "reports.view_sensitive",
    }
)

# Permissions that default to requiring an approval workflow. Values map to
# (threshold, required_role, num_approvers, expiry_minutes).
APPROVAL_GATED_PERMISSIONS = {
    "orders.process_refunds": ("3000", "admin", 2, 1440),
    "gift_cards.issue": ("5000", "admin", 1, 1440),
    "gift_cards.adjust_balance": ("1000", "admin", 1, 1440),
    "raw_materials.adjust_stock": ("50", "admin", 1, 1440),
    "customers.delete": ("0", "admin", 1, 1440),
    "products.change_prices": ("0", "admin", 1, 1440),
    "suppliers.record_payments": ("10000", "admin", 2, 1440),
    "finance.add_expenses": ("5000", "admin", 1, 1440),
    "tax.edit_settings": ("0", "super_admin", 1, 1440),
    "employees.grant_permissions": ("0", "admin", 1, 1440),
}

# Build lookup tables from the specs above.
ALL_PERMISSION_KEYS = tuple(
    key
    for _module, specs in PERMISSION_SPECS.items()
    for key, _label in specs
)
PERMISSION_LABELS = {
    key: label
    for _module, specs in PERMISSION_SPECS.items()
    for key, label in specs
}
MODULE_BY_PERMISSION = {
    key: module
    for module, specs in PERMISSION_SPECS.items()
    for key, _label in specs
}


def valid_permission(key):
    return key in PERMISSION_LABELS


# ── Default role permission matrix ────────────────────────────
def _keys(*keys):
    return {key for key in keys if valid_permission(key)}


_DASH_VIEW = _keys(
    "dashboard.view",
    "dashboard.view_sales_summary",
    "dashboard.view_branch_performance",
)
_ORDER_VIEW = _keys(
    "orders.view",
    "orders.view_customer_details",
)
_ORDER_MANAGE = _ORDER_VIEW | _keys(
    "orders.create",
    "orders.update_status",
    "orders.cancel",
    "orders.export",
)
_PRODUCT_VIEW = _keys("products.view")
_PRODUCT_MANAGE = _PRODUCT_VIEW | _keys(
    "products.create",
    "products.edit",
    "products.update_stock",
    "products.publish",
)
_RM_VIEW = _keys("raw_materials.view", "raw_materials.view_purchase_history")
_RM_MANAGE = _RM_VIEW | _keys(
    "raw_materials.create",
    "raw_materials.edit",
    "raw_materials.add_stock",
    "raw_materials.record_usage",
    "raw_materials.record_wastage",
    "raw_materials.record_damage",
    "raw_materials.record_supplier_payments",
    "raw_materials.export",
)
_CUST_VIEW = _keys(
    "customers.view",
    "customers.view_purchase_history",
)
_SUPPLIER_VIEW = _keys(
    "suppliers.view",
    "suppliers.view_payment_details",
)
_SUPPLIER_MANAGE = _SUPPLIER_VIEW | _keys(
    "suppliers.create",
    "suppliers.edit",
    "suppliers.create_purchase_orders",
    "suppliers.record_received",
    "suppliers.record_payments",
)
_AI_BASIC = _keys("ai.use_assistant", "ai.view_usage")

DEFAULT_ROLE_PERMISSIONS = {
    "super_admin": _keys(*ALL_PERMISSION_KEYS),
    "admin": _keys(*ALL_PERMISSION_KEYS),
    "branch_manager": (
        _DASH_VIEW
        | _ORDER_MANAGE
        | _PRODUCT_MANAGE
        | _RM_MANAGE
        | _CUST_VIEW
        | _keys(
            "customers.edit",
            "customers.view_contact_info",
            "customers.view_occasions",
            "customers.view_vip",
            "customers.flag_suspicious",
            "customers.suspend",
            "customers.restore",
            "customers.send_promotional_messages",
        )
        | _SUPPLIER_MANAGE
        | _AI_BASIC
        | _keys(
            "marketing.view",
            "marketing.create",
            "marketing.edit",
            "marketing.send_messages",
            "reports.view",
            "reports.export",
            "settings.view",
        )
    ),
    "store_manager": (
        _DASH_VIEW
        | _ORDER_MANAGE
        | _PRODUCT_MANAGE
        | _RM_MANAGE
        | _CUST_VIEW
        | _keys("customers.edit", "customers.view_contact_info")
        | _SUPPLIER_VIEW
        | _keys("suppliers.record_received")
        | _AI_BASIC
        | _keys("reports.view")
    ),
    "cashier": (
        _keys("dashboard.view")
        | _keys(
            "orders.view",
            "orders.create",
            "orders.update_status",
            "orders.cancel",
            "orders.view_customer_details",
        )
        | _keys("products.view", "products.update_stock")
        | _keys("raw_materials.view")
        | _keys("customers.view", "customers.view_contact_info")
        | _keys(
            "gift_cards.view",
            "gift_cards.issue",
            "gift_cards.collect_cash",
            "gift_cards.redeem",
        )
        | _AI_BASIC
    ),
    "finance_manager": (
        _keys(
            "dashboard.view",
            "dashboard.view_sales_summary",
            "dashboard.view_profit",
        )
        | _keys(
            "finance.view",
            "finance.view_revenue",
            "finance.view_expenses",
            "finance.add_expenses",
            "finance.edit_expenses",
            "finance.approve_expenses",
            "finance.view_transactions",
            "finance.view_profit",
            "finance.export",
        )
        | _keys(
            "tax.view_summary",
            "tax.view_transactions",
            "tax.export",
            "tax.view_business_number",
        )
        | _keys("reports.view", "reports.export", "reports.view_sensitive")
        | _SUPPLIER_VIEW
        | _keys("orders.view", "orders.export", "orders.view_customer_details")
        | _keys("employees.view")
    ),
    "inventory_manager": (
        _DASH_VIEW
        | _keys("raw_materials.view", "raw_materials.create", "raw_materials.edit")
        | _RM_MANAGE
        | _SUPPLIER_MANAGE
        | _keys(
            "products.view",
            "products.update_stock",
            "reports.view",
            "reports.export",
        )
        | _AI_BASIC
    ),
    "production_manager": (
        _DASH_VIEW
        | _keys(
            "products.view",
            "raw_materials.view",
            "raw_materials.add_stock",
            "raw_materials.record_usage",
            "raw_materials.record_wastage",
            "raw_materials.record_damage",
            "orders.view",
        )
    ),
    "order_manager": (
        _DASH_VIEW
        | _keys(
            "orders.view",
            "orders.create",
            "orders.update_status",
            "orders.cancel",
            "orders.approve_cancellations",
            "orders.export",
            "orders.view_customer_details",
        )
        | _CUST_VIEW
        | _keys("reports.view")
        | _AI_BASIC
    ),
    "delivery_manager": (
        _DASH_VIEW
        | _keys(
            "orders.view",
            "orders.update_status",
            "orders.view_customer_details",
        )
        | _keys("customers.view", "customers.view_contact_info")
        | _keys("reports.view")
    ),
    "customer_support": (
        _DASH_VIEW
        | _keys(
            "orders.view",
            "orders.view_customer_details",
            "customers.view",
            "customers.edit",
            "customers.view_contact_info",
            "customers.view_purchase_history",
            "customers.view_occasions",
            "customers.send_promotional_messages",
        )
        | _AI_BASIC
    ),
    "marketing_manager": (
        _DASH_VIEW
        | _CUST_VIEW
        | _keys(
            "customers.view_contact_info",
            "customers.send_promotional_messages",
            "customers.send_gifts",
        )
        | _keys(
            "marketing.view",
            "marketing.create",
            "marketing.edit",
            "marketing.approve",
            "marketing.send_messages",
            "marketing.view_consent",
            "marketing.export",
        )
        | _keys("reports.view", "reports.export")
    ),
    "employee": _keys(
        "dashboard.view",
        "orders.view",
        "products.view",
        "raw_materials.view",
        "customers.view",
        "reports.view",
    ),
    "read_only_staff": _keys(
        "dashboard.view",
        "orders.view",
        "products.view",
        "raw_materials.view",
        "customers.view",
        "suppliers.view",
        "gift_cards.view",
        "reports.view",
        "settings.view",
    ),
}

DEFAULT_ROLE_META = {
    "super_admin": {"name": "Super Admin", "description": "Unrestricted access to the entire portal.", "protected": True},
    "admin": {"name": "Admin", "description": "Full operational access across all modules."},
    "branch_manager": {"name": "Branch Manager", "description": "Runs a single branch end-to-end."},
    "store_manager": {"name": "Store Manager", "description": "Manages storefront operations and inventory."},
    "cashier": {"name": "Cashier", "description": "Counter orders, payments and gift cards at the POS."},
    "finance_manager": {"name": "Finance Manager", "description": "Finance, tax and expense management."},
    "inventory_manager": {"name": "Inventory Manager", "description": "Raw materials, stock and supplier purchasing."},
    "production_manager": {"name": "Production Manager", "description": "Kitchen production, batches and material usage."},
    "order_manager": {"name": "Order Manager", "description": "Order fulfilment, cancellations and approvals."},
    "delivery_manager": {"name": "Delivery Manager", "description": "Delivery operations and assigned staff."},
    "customer_support": {"name": "Customer Support", "description": "Customer care, order lookup and support."},
    "marketing_manager": {"name": "Marketing Manager", "description": "Campaigns, promotions and consent."},
    "employee": {"name": "Employee", "description": "Basic read access for general staff."},
    "read_only_staff": {"name": "Read-Only Staff", "description": "View-only access to operational modules."},
}

SUPER_ADMIN_ROLE_SLUG = "super_admin"
PROTECTED_ROLE_SLUGS = frozenset({"super_admin"})
