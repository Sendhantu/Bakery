from clock import utcnow
from .base import db


class RecurringSubscription(db.Model):
    __tablename__ = "recurring_subscriptions"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"))
    status = db.Column(db.String(20), default="active", nullable=False)
    frequency = db.Column(db.String(20), default="weekly", nullable=False)
    days_of_week = db.Column(db.String(30))
    next_scheduled_date = db.Column(db.Date, nullable=False)
    payment_method_reference = db.Column(
        db.String(80), default="manual_payment_link", nullable=False
    )
    paused_until = db.Column(db.Date)
    delivery_window = db.Column(db.String(50))
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=utcnow)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow)

    user = db.relationship(
        "User",
        backref=db.backref("recurring_order_subscriptions", lazy="dynamic"),
    )
    branch = db.relationship("Branch", backref="recurring_order_subscriptions")
    items = db.relationship(
        "SubscriptionItem",
        backref="subscription",
        lazy="dynamic",
        cascade="all, delete-orphan",
    )
    order_logs = db.relationship(
        "SubscriptionOrderLog",
        backref="subscription",
        lazy="dynamic",
        cascade="all, delete-orphan",
    )

    @property
    def normalized_status(self):
        return (self.status or "active").strip().lower()

    @property
    def days_of_week_list(self):
        values = []
        for raw in (self.days_of_week or "").split(","):
            raw = raw.strip()
            if not raw:
                continue
            try:
                day = int(raw)
            except ValueError:
                continue
            if 0 <= day <= 6:
                values.append(day)
        return sorted(set(values))


class SubscriptionItem(db.Model):
    __tablename__ = "subscription_items"
    id = db.Column(db.Integer, primary_key=True)
    subscription_id = db.Column(
        db.Integer, db.ForeignKey("recurring_subscriptions.id"), nullable=False
    )
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=False)
    variant_id = db.Column(db.Integer, db.ForeignKey("product_variants.id"))
    quantity = db.Column(db.Integer, nullable=False, default=1)

    product = db.relationship("Product")
    variant = db.relationship("ProductVariant")


class SubscriptionOrderLog(db.Model):
    __tablename__ = "subscription_order_logs"
    id = db.Column(db.Integer, primary_key=True)
    subscription_id = db.Column(
        db.Integer, db.ForeignKey("recurring_subscriptions.id"), nullable=False
    )
    order_id = db.Column(db.Integer, db.ForeignKey("orders.id"))
    attempted_at = db.Column(db.DateTime, default=utcnow, nullable=False)
    status = db.Column(db.String(40), nullable=False)
    notes = db.Column(db.Text)

    order = db.relationship("Order")
