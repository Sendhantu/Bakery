from datetime import datetime
import secrets

from clock import utcnow
from .base import db

PAYMENT_STATES = {
    "PENDING": {"AUTHORIZED", "PAID", "FAILED", "CANCELLED"},
    "AUTHORIZED": {"PAID", "FAILED", "CANCELLED", "REFUNDED"},
    "PAID": {"REFUNDED"},
    "FAILED": set(),
    "REFUNDED": set(),
    "CANCELLED": set(),
}

COUPON_AUDIENCE_ALL = "all"
COUPON_AUDIENCE_NEW_CUSTOMERS = "new_customers"
COUPON_AUDIENCE_RETURNING_CUSTOMERS = "returning_customers"

COUPON_AUDIENCE_CHOICES = (
    (COUPON_AUDIENCE_ALL, "All customers"),
    (COUPON_AUDIENCE_NEW_CUSTOMERS, "New customers - first order only"),
    (COUPON_AUDIENCE_RETURNING_CUSTOMERS, "Returning customers"),
)
COUPON_AUDIENCE_VALUES = {value for value, _label in COUPON_AUDIENCE_CHOICES}
COUPON_AUDIENCE_LABELS = dict(COUPON_AUDIENCE_CHOICES)


class Payment(db.Model):
    __tablename__ = "payments"
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("orders.id"), nullable=False)
    amount = db.Column(db.Numeric(10, 2), nullable=False)
    status = db.Column(db.String(30), default="PENDING")
    transaction_id = db.Column(db.String(100))
    method         = db.Column(db.String(50))
    gateway_name = db.Column(db.String(50))
    gateway_payload = db.Column(db.Text)
    authorized_at = db.Column(db.DateTime)
    paid_at = db.Column(db.DateTime)
    failed_at = db.Column(db.DateTime)
    refunded_at = db.Column(db.DateTime)
    cancelled_at = db.Column(db.DateTime)
    failure_reason = db.Column(db.String(255))
    version = db.Column(db.Integer, default=1, nullable=False)
    created_at = db.Column(db.DateTime, default=utcnow)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow)

    transitions = db.relationship(
        "PaymentTransitionLog",
        backref="payment",
        lazy="dynamic",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        db.Index("idx_payment_order_id", "order_id"),
        db.Index("idx_payment_status_created", "status", "created_at"),
    )

    def can_transition_to(self, new_state):
        current_state = (self.status or "PENDING").strip().upper()
        new_state = (new_state or "").strip().upper()
        return new_state == current_state or new_state in PAYMENT_STATES.get(
            current_state, set()
        )

    def transition_to(self, new_state, actor_id=None, reason=""):
        new_state = (new_state or "").strip().upper()
        current_state = (self.status or "PENDING").strip().upper()
        if not self.can_transition_to(new_state):
            raise ValueError(
                f"Invalid payment transition from {current_state} to {new_state}"
            )

        now = utcnow()
        self.status = new_state
        self.version = int(self.version or 0) + 1
        self.updated_at = now

        if new_state == "AUTHORIZED":
            self.authorized_at = now
        elif new_state == "PAID":
            self.paid_at = now
        elif new_state == "FAILED":
            self.failed_at = now
            self.failure_reason = reason or self.failure_reason
        elif new_state == "REFUNDED":
            self.refunded_at = now
        elif new_state == "CANCELLED":
            self.cancelled_at = now

        if self.order is not None:
            self.order.payment_status = new_state
        elif self.order_id:
            from .order import Order

            related_order = db.session.get(Order, self.order_id)
            if related_order is not None:
                related_order.payment_status = new_state

        db.session.add(
            PaymentTransitionLog(
                payment=self,
                previous_state=current_state,
                next_state=new_state,
                actor_id=actor_id,
                reason=reason,
            )
        )
        if new_state == "PAID":
            try:
                from services.finance_service import maybe_record_sale_on_payment

                maybe_record_sale_on_payment(self, actor_id=actor_id)
            except Exception:
                pass
        return self


class PaymentLink(db.Model):
    """A lightweight payment link record.

    This model stores metadata and a token for redirecting customers to a
    payment provider. It intentionally does not store raw payment credentials
    such as card numbers, CVV, or UPI PINs.
    """
    __tablename__ = "payment_links"
    id = db.Column(db.Integer, primary_key=True)
    token = db.Column(db.String(64), unique=True, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    order_id = db.Column(db.Integer, db.ForeignKey("orders.id"))
    purpose = db.Column(db.String(30), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    amount = db.Column(db.Numeric(10, 2), nullable=False)
    payment_method = db.Column(db.String(50), default="UPI")
    status = db.Column(db.String(30), default="PENDING")
    subscription_plan = db.Column(db.String(20))
    subscription_discount_pct  = db.Column(db.Numeric(5, 2))
    subscription_duration_days = db.Column(db.Integer)
    success_url = db.Column(db.String(255))
    cancel_url = db.Column(db.String(255))
    gateway_reference = db.Column(db.String(100))
    notes = db.Column(db.Text)
    expires_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=utcnow)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow)

    @classmethod
    def create_pending(cls, **kwargs):
        purpose = kwargs.get('purpose')
        user_id = kwargs.get('user_id')
        order_id = kwargs.get('order_id')
        subscription_plan = kwargs.get('subscription_plan')

        q = cls.query.filter_by(user_id=user_id, purpose=purpose, status="PENDING")
        q = q.filter(cls.order_id.is_(None)) if order_id is None else q.filter_by(order_id=order_id)
        if purpose == "SUBSCRIPTION" and subscription_plan:
            q = q.filter_by(subscription_plan=subscription_plan)
        existing = q.order_by(cls.id.desc()).first()
        if existing:
            for k, v in kwargs.items():
                setattr(existing, k, v)
            if not existing.token:
                existing.token = secrets.token_urlsafe(24)
            return existing

        link = cls(**kwargs)
        link.token = secrets.token_urlsafe(24)
        db.session.add(link)
        return link


class Refund(db.Model):
    __tablename__ = "refunds"
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("orders.id"), nullable=False)
    amount = db.Column(db.Numeric(10, 2), nullable=False)
    reason    = db.Column(db.String(255))
    status    = db.Column(db.String(30), default="PENDING")
    timestamp = db.Column(db.DateTime, default=utcnow)


class Coupon(db.Model):
    __tablename__ = "coupons"
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(50), unique=True, nullable=False)
    discount_type = db.Column(db.String(20), default="percentage")
    discount_value  = db.Column(db.Numeric(10, 2), nullable=False)
    min_order_value = db.Column(db.Numeric(10, 2), default=0)
    max_uses        = db.Column(db.Integer, default=100)
    used_count      = db.Column(db.Integer, default=0)
    per_user_limit = db.Column(db.Integer, default=1)
    customer_audience = db.Column(
        db.String(30), default=COUPON_AUDIENCE_ALL, nullable=False
    )
    first_order_only = db.Column(db.Boolean, default=False, nullable=False)
    valid_from      = db.Column(db.DateTime)
    valid_until     = db.Column(db.DateTime)
    is_active = db.Column(db.Boolean, default=True)

    def is_valid(self):
        now = utcnow()
        if not self.is_active or self.used_count >= self.max_uses:
            return False
        if self.valid_from and now < self.valid_from:
            return False
        if self.valid_until and now > self.valid_until:
            return False
        return True

    @property
    def normalized_customer_audience(self):
        audience = (self.customer_audience or COUPON_AUDIENCE_ALL).strip().lower()
        return audience if audience in COUPON_AUDIENCE_VALUES else COUPON_AUDIENCE_ALL

    @property
    def audience_label(self):
        if self.first_order_only:
            return COUPON_AUDIENCE_LABELS[COUPON_AUDIENCE_NEW_CUSTOMERS]
        return COUPON_AUDIENCE_LABELS[self.normalized_customer_audience]

    def eligibility_message(self, prior_order_count):
        prior_orders = int(prior_order_count or 0)
        audience = self.normalized_customer_audience
        if self.first_order_only or audience == COUPON_AUDIENCE_NEW_CUSTOMERS:
            if prior_orders > 0:
                return "This welcome coupon is only for a customer's first order."
        if audience == COUPON_AUDIENCE_RETURNING_CUSTOMERS and prior_orders <= 0:
            return "This coupon is only for returning customers."
        return None

    def is_eligible_for_customer(self, prior_order_count):
        return self.eligibility_message(prior_order_count) is None


class PaymentTransitionLog(db.Model):
    __tablename__ = "payment_transition_logs"
    id = db.Column(db.Integer, primary_key=True)
    payment_id = db.Column(db.Integer, db.ForeignKey("payments.id"), nullable=False)
    actor_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    previous_state = db.Column(db.String(30), nullable=False)
    next_state = db.Column(db.String(30), nullable=False)
    reason = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=utcnow)

    actor = db.relationship("User")
