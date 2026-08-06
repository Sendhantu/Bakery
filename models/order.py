from datetime import datetime, timedelta
from decimal import Decimal
import uuid

from clock import utcnow
from .base import db

ORDER_STATUSES = [
    "PLACED",
    "PREPARING",
    "PACKED",
    "OUT_FOR_DELIVERY",
    "DELIVERED",
    "CANCELLED",
    "REFUNDED",
    "ON_HOLD",
    "READY_FOR_PICKUP",
]
PAYMENT_STATES = [
    "PENDING",
    "AUTHORIZED",
    "PAID",
    "FAILED",
    "REFUNDED",
    "CANCELLED",
]
ORDER_STATUS_TRANSITIONS = {
    "PLACED": ["PREPARING", "PACKED", "READY_FOR_PICKUP", "ON_HOLD", "CANCELLED"],
    "PREPARING": ["PACKED", "READY_FOR_PICKUP", "ON_HOLD", "CANCELLED"],
    "PACKED": [
        "OUT_FOR_DELIVERY",
        "READY_FOR_PICKUP",
        "DELIVERED",
        "ON_HOLD",
        "CANCELLED",
    ],
    "READY_FOR_PICKUP": ["DELIVERED", "ON_HOLD", "CANCELLED"],
    "OUT_FOR_DELIVERY": ["DELIVERED", "ON_HOLD"],
    "ON_HOLD": [
        "PREPARING",
        "PACKED",
        "READY_FOR_PICKUP",
        "OUT_FOR_DELIVERY",
        "CANCELLED",
    ],
    "DELIVERED": [],
    "CANCELLED": [],
    "REFUNDED": [],
}
ORDER_CUSTOMER_CANCEL_WINDOW = timedelta(minutes=2)
ORDER_CUSTOMER_CANCEL_WINDOW_SECONDS = int(
    ORDER_CUSTOMER_CANCEL_WINDOW.total_seconds()
)

GST_SUPPLY_RESTAURANT_SERVICE = "RESTAURANT_SERVICE"
GST_LIABILITY_BAKERY = "PAYABLE_BY_BAKERY"
GST_LIABILITY_ECOMMERCE_OPERATOR = "PAID_BY_ECOMMERCE_OPERATOR"
GST_RETURN_OUTWARD_SUPPLIES = "GSTR1_OUTWARD_SUPPLIES"
GST_RETURN_ECOMMERCE_9_5 = "GSTR1_TABLE_14_9_5"

GST_ORDER_SOURCE_COUNTER_DINE_IN = "COUNTER_DINE_IN"
GST_ORDER_SOURCE_COUNTER_TAKEAWAY = "COUNTER_TAKEAWAY"
GST_ORDER_SOURCE_DIRECT_WEB_DELIVERY = "DIRECT_WEB_DELIVERY"
GST_ORDER_SOURCE_DIRECT_WEB_PICKUP = "DIRECT_WEB_PICKUP"
GST_ORDER_SOURCE_ECOMMERCE_SWIGGY = "ECOMMERCE_SWIGGY"
GST_ORDER_SOURCE_ECOMMERCE_ZOMATO = "ECOMMERCE_ZOMATO"

GST_ORDER_SOURCE_CHOICES = [
    (GST_ORDER_SOURCE_COUNTER_DINE_IN, "Counter dine-in"),
    (GST_ORDER_SOURCE_COUNTER_TAKEAWAY, "Counter takeaway"),
    (GST_ORDER_SOURCE_DIRECT_WEB_DELIVERY, "Direct web delivery"),
    (GST_ORDER_SOURCE_DIRECT_WEB_PICKUP, "Direct web pickup"),
    (GST_ORDER_SOURCE_ECOMMERCE_SWIGGY, "Swiggy - Section 9(5)"),
    (GST_ORDER_SOURCE_ECOMMERCE_ZOMATO, "Zomato - Section 9(5)"),
]
GST_ORDER_SOURCE_LABELS = dict(GST_ORDER_SOURCE_CHOICES)
GST_ORDER_SOURCE_VALUES = {value for value, _label in GST_ORDER_SOURCE_CHOICES}
GST_ECOMMERCE_ORDER_SOURCES = {
    GST_ORDER_SOURCE_ECOMMERCE_SWIGGY,
    GST_ORDER_SOURCE_ECOMMERCE_ZOMATO,
}
GST_ECOMMERCE_OPERATOR_BY_SOURCE = {
    GST_ORDER_SOURCE_ECOMMERCE_SWIGGY: "SWIGGY",
    GST_ORDER_SOURCE_ECOMMERCE_ZOMATO: "ZOMATO",
}
GST_LIABILITY_LABELS = {
    GST_LIABILITY_BAKERY: "Payable by Bakery",
    GST_LIABILITY_ECOMMERCE_OPERATOR: "Paid by Aggregator",
}


def get_allowed_order_statuses(current_status, actor="admin"):
    current_status = (current_status or "PLACED").strip().upper()
    if actor == "delivery":
        allowed = [
            status
            for status in ORDER_STATUS_TRANSITIONS.get(current_status, [])
            if status in {"OUT_FOR_DELIVERY", "DELIVERED", "READY_FOR_PICKUP"}
        ]
    else:
        allowed = list(ORDER_STATUS_TRANSITIONS.get(current_status, []))
    return [current_status] + [status for status in allowed if status != current_status]


def can_transition_order_status(current_status, new_status, actor="admin"):
    new_status = (new_status or "").strip().upper()
    return new_status in get_allowed_order_statuses(current_status, actor=actor)


class Order(db.Model):
    __tablename__ = "orders"
    id = db.Column(db.Integer, primary_key=True)
    order_number = db.Column(db.String(20), unique=True, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"))
    status = db.Column(db.String(30), default="PLACED")
    source = db.Column(db.String(20), default="WEB")
    channel = db.Column(db.String(20), default="online", nullable=False)
    subtotal = db.Column(db.Numeric(10, 2), default=0)
    discount = db.Column(db.Numeric(10, 2), default=0)
    loyalty_discount = db.Column(
        db.Numeric(10, 2), default=0
    )  # NEW: loyalty redemption amount
    gift_card_redemption_amount = db.Column(db.Numeric(10, 2), default=0)
    gift_card_code = db.Column(db.String(40))
    delivery_charge = db.Column(db.Numeric(10, 2), default=0)
    gst_rate = db.Column(db.Numeric(5, 2), default=5)
    gst_amount = db.Column(db.Numeric(10, 2), default=0)
    gst_taxable_amount = db.Column(db.Numeric(10, 2), default=0)
    cgst_amount = db.Column(db.Numeric(10, 2), default=0)
    sgst_amount = db.Column(db.Numeric(10, 2), default=0)
    gst_supply_type = db.Column(
        db.String(40), default=GST_SUPPLY_RESTAURANT_SERVICE, nullable=False
    )
    gst_order_source = db.Column(
        db.String(40), default=GST_ORDER_SOURCE_DIRECT_WEB_DELIVERY, nullable=False
    )
    gst_liability_party = db.Column(
        db.String(40), default=GST_LIABILITY_BAKERY, nullable=False
    )
    gst_return_bucket = db.Column(
        db.String(40), default=GST_RETURN_OUTWARD_SUPPLIES, nullable=False
    )
    gst_invoice_note = db.Column(db.String(255))
    ecommerce_operator = db.Column(db.String(40))
    ecommerce_tcs_amount = db.Column(db.Numeric(10, 2), default=0)
    total = db.Column(db.Numeric(10, 2), default=0)

    address_line1 = db.Column(db.String(255))
    address_line2 = db.Column(db.String(255))
    city = db.Column(db.String(100))
    pincode = db.Column(db.String(10))
    phone = db.Column(db.String(20))
    fulfillment_type = db.Column(db.String(20), default="DELIVERY")
    delivery_latitude = db.Column(db.Float)
    delivery_longitude = db.Column(db.Float)

    delivery_slot = db.Column(db.String(50))
    delivery_date = db.Column(db.Date)
    special_note = db.Column(db.Text)
    occasion = db.Column(db.String(100))

    payment_method = db.Column(db.String(50), default="COD")
    payment_status = db.Column(db.String(30), default="PENDING")
    coupon_code = db.Column(db.String(50))
    invoice_number = db.Column(db.String(40), unique=True)
    invoice_url = db.Column(db.String(255))
    qr_token = db.Column(db.String(80), unique=True)
    qr_verified_at = db.Column(db.DateTime)
    qr_verified_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    version = db.Column(db.Integer, default=1, nullable=False)
    sync_version = db.Column(db.Integer, default=1, nullable=False)
    last_synced_at = db.Column(db.DateTime)
    sync_status = db.Column(db.String(20), default="SYNCED")
    idempotency_key = db.Column(db.String(80), unique=True)
    is_suspicious = db.Column(db.Boolean, default=False)

    placed_at = db.Column(db.DateTime, default=utcnow)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow)
    is_locked = db.Column(db.Boolean, default=False)
    address_changes = db.Column(db.Integer, default=0)

    items = db.relationship(
        "OrderItem",
        backref="order",
        lazy="dynamic",
        cascade="all, delete-orphan",
    )
    payment = db.relationship("Payment", backref="order", uselist=False)
    payment_links = db.relationship("PaymentLink", backref="order", lazy="dynamic")
    refunds = db.relationship("Refund", backref="order", lazy="dynamic")
    delivery = db.relationship("Delivery", backref="order", uselist=False)
    addr_history = db.relationship("AddressChange", backref="order", lazy="dynamic")
    mod_requests = db.relationship(
        "ModificationRequest", backref="order", lazy="dynamic"
    )
    loyalty_entries = db.relationship(
        "LoyaltyLedger",
        backref="order",
        lazy="dynamic",
        foreign_keys="LoyaltyLedger.order_id",
    )
    branch = db.relationship("Branch", backref="orders")

    __table_args__ = (
        db.Index("idx_order_user", "user_id"),
        db.Index("idx_order_status", "status"),
        db.Index(
            "idx_order_status_payment_placed", "status", "payment_status", "placed_at"
        ),
        db.Index(
            "idx_order_branch_status_date", "branch_id", "status", "delivery_date"
        ),
        db.Index("idx_order_user_status_placed", "user_id", "status", "placed_at"),
    )

    def can_cancel(self):
        if (self.status or "").upper() != "PLACED" or not self.placed_at:
            return False
        return utcnow() <= self.customer_cancel_deadline()

    def customer_cancel_deadline(self):
        if not self.placed_at:
            return None
        return self.placed_at + ORDER_CUSTOMER_CANCEL_WINDOW

    def customer_cancel_seconds_remaining(self):
        deadline = self.customer_cancel_deadline()
        if deadline is None:
            return 0
        return max(0, int((deadline - utcnow()).total_seconds()))

    def customer_cancel_window_seconds(self):
        return ORDER_CUSTOMER_CANCEL_WINDOW_SECONDS

    @property
    def gst_order_source_label(self):
        return GST_ORDER_SOURCE_LABELS.get(
            self.gst_order_source or GST_ORDER_SOURCE_DIRECT_WEB_DELIVERY,
            self.gst_order_source or "Direct sale",
        )

    @property
    def gst_liability_label(self):
        return GST_LIABILITY_LABELS.get(
            self.gst_liability_party or GST_LIABILITY_BAKERY,
            self.gst_liability_party or "Payable by Bakery",
        )

    @property
    def gst_paid_by_ecommerce_operator(self):
        return (
            (self.gst_liability_party or "").upper()
            == GST_LIABILITY_ECOMMERCE_OPERATOR
        )

    @property
    def gst_payable_by_bakery(self):
        return not self.gst_paid_by_ecommerce_operator

    @property
    def ecommerce_tcs_due(self):
        return Decimal(str(self.ecommerce_tcs_amount or 0)).quantize(
            Decimal("0.01")
        )

    def can_modify(self):
        return self.status in ["PLACED"] and not self.is_locked

    def can_change_address(self):
        if (self.fulfillment_type or "DELIVERY").upper() == "PICKUP":
            return False
        return (
            self.status not in ["OUT_FOR_DELIVERY", "DELIVERED", "CANCELLED"]
            and self.address_changes < 2
        )

    def mark_status_change(self):
        self.version = int(self.version or 0) + 1
        self.sync_version = int(self.sync_version or 0) + 1
        self.updated_at = utcnow()

    @staticmethod
    def generate_order_number():
        """UUID-based — zero collision risk."""
        prefix = utcnow().strftime("%Y%m%d")
        suffix = uuid.uuid4().hex[:6].upper()
        return f"SC{prefix}{suffix}"


class OrderItem(db.Model):
    __tablename__ = "order_items"
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("orders.id"), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=False)
    variant_id = db.Column(db.Integer, db.ForeignKey("product_variants.id"))
    product_name = db.Column(db.String(200))
    variant_name = db.Column(db.String(100))
    quantity = db.Column(db.Integer, nullable=False)
    unit_price = db.Column(db.Numeric(10, 2), nullable=False)
    subtotal = db.Column(db.Numeric(10, 2), nullable=False)
    variant = db.relationship("ProductVariant")

    __table_args__ = (
        db.Index("idx_order_item_order", "order_id"),
        db.Index("idx_order_item_product", "product_id"),
    )


class AddressChange(db.Model):
    __tablename__ = "address_changes"
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("orders.id"), nullable=False)
    old_address = db.Column(db.Text)
    new_address = db.Column(db.Text)
    changed_at = db.Column(db.DateTime, default=utcnow)
    changed_by = db.Column(db.Integer, db.ForeignKey("users.id"))


class ModificationRequest(db.Model):
    __tablename__ = "modification_requests"
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("orders.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    description = db.Column(db.Text)
    status = db.Column(db.String(20), default="PENDING")
    price_diff = db.Column(db.Numeric(10, 2), default=0)
    created_at = db.Column(db.DateTime, default=utcnow)
    resolved_at = db.Column(db.DateTime)
