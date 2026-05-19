from datetime import datetime, timedelta
import uuid

from .base import db

ORDER_STATUSES = [
    "PLACED",
    "PREPARING",
    "PACKED",
    "OUT_FOR_DELIVERY",
    "DELIVERED",
    "CANCELLED",
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
    "ON_HOLD": ["PREPARING", "PACKED", "READY_FOR_PICKUP", "OUT_FOR_DELIVERY", "CANCELLED"],
    "DELIVERED": [],
    "CANCELLED": [],
}

def get_allowed_order_statuses(current_status, actor='admin'):
    current_status = (current_status or 'PLACED').strip().upper()
    if actor == 'delivery':
        allowed = [
            status
            for status in ORDER_STATUS_TRANSITIONS.get(current_status, [])
            if status in {"OUT_FOR_DELIVERY", "DELIVERED", "READY_FOR_PICKUP"}
        ]
    else:
        allowed = list(ORDER_STATUS_TRANSITIONS.get(current_status, []))
    return [current_status] + [status for status in allowed if status != current_status]


def can_transition_order_status(current_status, new_status, actor='admin'):
    new_status = (new_status or '').strip().upper()
    return new_status in get_allowed_order_statuses(current_status, actor=actor)


class Order(db.Model):
    __tablename__ = "orders"
    id = db.Column(db.Integer, primary_key=True)
    order_number = db.Column(db.String(20), unique=True, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"))
    status = db.Column(db.String(30), default="PLACED")
    source = db.Column(db.String(20), default="WEB")
    subtotal = db.Column(db.Numeric(10, 2), default=0)
    discount = db.Column(db.Numeric(10, 2), default=0)
    loyalty_discount = db.Column(db.Numeric(10, 2), default=0)  # NEW: loyalty redemption amount
    delivery_charge = db.Column(db.Numeric(10, 2), default=0)
    gst_rate = db.Column(db.Numeric(5, 2), default=5)
    gst_amount = db.Column(db.Numeric(10, 2), default=0)
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

    placed_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
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
        db.Index("idx_order_branch_status_date", "branch_id", "status", "delivery_date"),
        db.Index("idx_order_user_status_placed", "user_id", "status", "placed_at"),
    )

    def can_cancel(self):
        if self.status not in ["PLACED"]:
            return False
        window = self.placed_at + timedelta(minutes=2)
        return datetime.utcnow() <= window

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
        self.updated_at = datetime.utcnow()

    @staticmethod
    def generate_order_number():
        """UUID-based — zero collision risk."""
        prefix = datetime.utcnow().strftime("%Y%m%d")
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


class AddressChange(db.Model):
    __tablename__ = "address_changes"
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("orders.id"), nullable=False)
    old_address = db.Column(db.Text)
    new_address = db.Column(db.Text)
    changed_at = db.Column(db.DateTime, default=datetime.utcnow)
    changed_by = db.Column(db.Integer, db.ForeignKey("users.id"))


class ModificationRequest(db.Model):
    __tablename__ = "modification_requests"
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("orders.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    description = db.Column(db.Text)
    status = db.Column(db.String(20), default="PENDING")
    price_diff = db.Column(db.Numeric(10, 2), default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    resolved_at = db.Column(db.DateTime)
