from datetime import datetime
import secrets
from .base import db

class Payment(db.Model):
    __tablename__ = 'payments'
    id             = db.Column(db.Integer, primary_key=True)
    order_id       = db.Column(db.Integer, db.ForeignKey('orders.id'), nullable=False)
    amount         = db.Column(db.Numeric(10, 2), nullable=False)
    status         = db.Column(db.String(30), default='PENDING')
    transaction_id = db.Column(db.String(100))
    method         = db.Column(db.String(50))
    created_at     = db.Column(db.DateTime, default=datetime.utcnow)


class PaymentLink(db.Model):
    """A lightweight payment link record.

    This model stores metadata and a token for redirecting customers to a
    payment provider. It intentionally does not store raw payment credentials
    such as card numbers, CVV, or UPI PINs.
    """
    __tablename__ = 'payment_links'
    id                         = db.Column(db.Integer, primary_key=True)
    token                      = db.Column(db.String(64), unique=True, nullable=False)
    user_id                    = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    order_id                   = db.Column(db.Integer, db.ForeignKey('orders.id'))
    purpose                    = db.Column(db.String(30), nullable=False)
    title                      = db.Column(db.String(200), nullable=False)
    amount                     = db.Column(db.Numeric(10, 2), nullable=False)
    payment_method             = db.Column(db.String(50), default='UPI')
    status                     = db.Column(db.String(30), default='PENDING')
    subscription_plan          = db.Column(db.String(20))
    subscription_discount_pct  = db.Column(db.Numeric(5, 2))
    subscription_duration_days = db.Column(db.Integer)
    success_url                = db.Column(db.String(255))
    cancel_url                 = db.Column(db.String(255))
    gateway_reference          = db.Column(db.String(100))
    notes                      = db.Column(db.Text)
    created_at                 = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at                 = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    @classmethod
    def create_pending(cls, **kwargs):
        purpose = kwargs.get('purpose')
        user_id = kwargs.get('user_id')
        order_id = kwargs.get('order_id')
        subscription_plan = kwargs.get('subscription_plan')

        q = cls.query.filter_by(user_id=user_id, purpose=purpose, status='PENDING')
        q = q.filter(cls.order_id.is_(None)) if order_id is None else q.filter_by(order_id=order_id)
        if purpose == 'SUBSCRIPTION' and subscription_plan:
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
    __tablename__ = 'refunds'
    id        = db.Column(db.Integer, primary_key=True)
    order_id  = db.Column(db.Integer, db.ForeignKey('orders.id'), nullable=False)
    amount    = db.Column(db.Numeric(10, 2), nullable=False)
    reason    = db.Column(db.String(255))
    status    = db.Column(db.String(30), default='PENDING')
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)


class Coupon(db.Model):
    __tablename__ = 'coupons'
    id              = db.Column(db.Integer, primary_key=True)
    code            = db.Column(db.String(50), unique=True, nullable=False)
    discount_type   = db.Column(db.String(20), default='percentage')
    discount_value  = db.Column(db.Numeric(10, 2), nullable=False)
    min_order_value = db.Column(db.Numeric(10, 2), default=0)
    max_uses        = db.Column(db.Integer, default=100)
    used_count      = db.Column(db.Integer, default=0)
    valid_from      = db.Column(db.DateTime)
    valid_until     = db.Column(db.DateTime)
    is_active       = db.Column(db.Boolean, default=True)

    def is_valid(self):
        now = datetime.utcnow()
        if not self.is_active or self.used_count >= self.max_uses:
            return False
        if self.valid_from and now < self.valid_from:
            return False
        if self.valid_until and now > self.valid_until:
            return False
        return True
