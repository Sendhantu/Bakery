from datetime import datetime
from flask_login import UserMixin
from sqlalchemy import func, or_
from .base import db, bcrypt
from .loyalty import LoyaltyLedger

class User(UserMixin, db.Model):
    __tablename__ = 'users'
    id         = db.Column(db.Integer, primary_key=True)
    name       = db.Column(db.String(100), nullable=False)
    email      = db.Column(db.String(120), unique=True, nullable=False)
    phone      = db.Column(db.String(20))
    password   = db.Column(db.String(255), nullable=True)
    role       = db.Column(db.Enum('customer', 'admin', 'delivery'), default='customer')
    permissions = db.Column(db.Text, default='[]')
    is_active  = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    avatar     = db.Column(db.String(255), default='default.png')

    oauth_id       = db.Column(db.String(100), unique=True)
    oauth_provider = db.Column(db.String(50))

    # Relationships
    orders         = db.relationship('Order', backref='customer', lazy='dynamic', foreign_keys='Order.user_id')
    cart_items     = db.relationship('Cart', backref='user', lazy='dynamic')
    wishlist_items = db.relationship('Wishlist', backref='user', lazy='dynamic')
    reviews        = db.relationship('Review', backref='author', lazy='dynamic')
    messages_sent  = db.relationship('Message', backref='sender', lazy='dynamic', foreign_keys='Message.sender_id')
    login_history  = db.relationship('LoginHistory', backref='user', lazy='dynamic')
    subscription   = db.relationship('Subscription', backref='user', uselist=False)
    notifications  = db.relationship('Notification', backref='user', lazy='dynamic')
    payment_links  = db.relationship('PaymentLink', backref='user', lazy='dynamic')
    loyalty_ledger = db.relationship('LoyaltyLedger', backref='user', lazy='dynamic', foreign_keys='LoyaltyLedger.user_id')
    saved_addresses = db.relationship('SavedAddress', backref='user', lazy='dynamic', cascade='all, delete-orphan')

    def set_password(self, password):
        self.password = bcrypt.generate_password_hash(password).decode('utf-8')

    def check_password(self, password):
        return bcrypt.check_password_hash(self.password, password)

    @property
    def loyalty_points(self):
        """Sum of non-expired active points in the ledger."""
        now = datetime.utcnow()
        total = db.session.query(
            func.coalesce(func.sum(LoyaltyLedger.points), 0)
        ).filter(
            LoyaltyLedger.user_id == self.id,
            or_(LoyaltyLedger.expires_at.is_(None), LoyaltyLedger.expires_at > now),
        ).scalar()
        return max(0, int(total or 0))

    @property
    def loyalty_tier(self):
        pts = self.loyalty_points
        if pts >= 1000: return 'Gold'
        if pts >= 500:  return 'Silver'
        return 'Bronze'

    def __repr__(self):
        return f'<User {self.email}>'


class LoginHistory(db.Model):
    __tablename__ = 'login_history'
    id         = db.Column(db.Integer, primary_key=True)
    user_id    = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    login_time = db.Column(db.DateTime, default=datetime.utcnow)
    ip_address = db.Column(db.String(50))
    device     = db.Column(db.String(200))
    status     = db.Column(db.String(20), default='success')


class Subscription(db.Model):
    __tablename__ = 'subscriptions'
    id           = db.Column(db.Integer, primary_key=True)
    user_id      = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    plan         = db.Column(db.String(20), default='monthly')
    discount_pct = db.Column(db.Numeric(5, 2), default=10)
    start_date   = db.Column(db.DateTime, default=datetime.utcnow)
    end_date     = db.Column(db.DateTime)
    is_active    = db.Column(db.Boolean, default=True)
    price_paid   = db.Column(db.Numeric(10, 2))
