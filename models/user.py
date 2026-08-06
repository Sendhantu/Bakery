from datetime import datetime
import secrets

from clock import utcnow
from flask_login import UserMixin
from sqlalchemy import func, or_

from .base import db, bcrypt
from .loyalty import LoyaltyLedger


class User(UserMixin, db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    phone = db.Column(db.String(20))
    password = db.Column(db.String(255), nullable=True)
    role = db.Column(
        db.String(40),
        default="customer",
        nullable=False,
    )
    permissions = db.Column(db.Text, default="[]")
    admin_tier = db.Column(db.String(20), default="owner", nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"))
    staff_address = db.Column(db.Text)
    date_of_joining = db.Column(db.Date)
    designation = db.Column(db.String(120))
    emergency_contact = db.Column(db.String(50))
    staff_notes = db.Column(db.Text)
    email_locked = db.Column(db.Boolean, default=False, nullable=False)
    birthday = db.Column(db.Date)
    referral_code = db.Column(
        db.String(32),
        unique=True,
        nullable=False,
        default=lambda: secrets.token_hex(4).upper(),
    )
    referred_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    wallet_balance = db.Column(db.Numeric(10, 2), default=0)
    is_mobile_verified = db.Column(db.Boolean, default=False)
    must_change_password = db.Column(db.Boolean, default=False, nullable=False)
    password_changed_at = db.Column(db.DateTime)
    last_seen_at = db.Column(db.DateTime, default=utcnow)
    created_at = db.Column(db.DateTime, default=utcnow)
    avatar = db.Column(db.String(255), default="default.png")

    oauth_id = db.Column(db.String(100), unique=True)
    oauth_provider = db.Column(db.String(50))

    # ── RBAC / employee management ──────────────────────────────
    rbac_enabled = db.Column(db.Boolean, default=False, nullable=False)
    employee_status = db.Column(db.String(30), default="active", nullable=False)
    employment_status = db.Column(db.String(30), default="full_time")
    employee_id = db.Column(db.String(40), index=True)
    department = db.Column(db.String(80))
    job_title = db.Column(db.String(120))
    invite_token = db.Column(db.String(64), index=True)
    invite_token_expires_at = db.Column(db.DateTime)
    invited_at = db.Column(db.DateTime)
    invite_accepted_at = db.Column(db.DateTime)
    force_logout_before = db.Column(db.DateTime)
    branch_scope = db.Column(db.String(20), default="all", nullable=False)
    created_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    last_login_at = db.Column(db.DateTime)

    # Relationships
    orders = db.relationship(
        "Order",
        backref="customer",
        lazy="dynamic",
        foreign_keys="Order.user_id",
    )
    cart_items = db.relationship("Cart", backref="user", lazy="dynamic")
    wishlist_items = db.relationship("Wishlist", backref="user", lazy="dynamic")
    reviews = db.relationship("Review", backref="author", lazy="dynamic")
    messages_sent = db.relationship(
        "Message",
        backref="sender",
        lazy="dynamic",
        foreign_keys="Message.sender_id",
    )
    login_history = db.relationship("LoginHistory", backref="user", lazy="dynamic")
    subscription = db.relationship("Subscription", backref="user", uselist=False)
    notifications = db.relationship("Notification", backref="user", lazy="dynamic")
    payment_links = db.relationship("PaymentLink", backref="user", lazy="dynamic")
    loyalty_ledger = db.relationship(
        "LoyaltyLedger",
        backref="user",
        lazy="dynamic",
        foreign_keys="LoyaltyLedger.user_id",
    )
    saved_addresses = db.relationship(
        "SavedAddress",
        backref="user",
        lazy="dynamic",
        cascade="all, delete-orphan",
    )
    staff_shifts = db.relationship("StaffShift", backref="staff_user", lazy="dynamic")
    attendance_records = db.relationship(
        "AttendanceRecord",
        backref="staff_user",
        lazy="dynamic",
        foreign_keys="AttendanceRecord.user_id",
    )
    branch = db.relationship("Branch", backref="staff_members")
    created_by = db.relationship(
        "User",
        remote_side=[id],
        foreign_keys=[created_by_id],
    )
    referred_customers = db.relationship(
        "User",
        backref=db.backref("referrer", remote_side=[id]),
        lazy="dynamic",
    )

    __table_args__ = (
        db.Index("idx_users_role_active_branch", "role", "is_active", "branch_id"),
    )

    def set_password(self, password, *, require_change=False):
        self.password = bcrypt.generate_password_hash(password).decode("utf-8")
        self.password_changed_at = utcnow()
        self.must_change_password = bool(require_change)

    def check_password(self, password):
        if not self.password:
            return False
        return bcrypt.check_password_hash(self.password, password)

    def has_role(self, role_name):
        return (self.role or "").strip().lower() == (role_name or "").strip().lower()

    def has_any_role(self, *role_names):
        normalized = {(role or "").strip().lower() for role in role_names}
        return (self.role or "").strip().lower() in normalized

    @property
    def effective_admin_tier(self):
        role = (self.role or "").strip().lower()
        if role == "super_admin":
            return "owner"
        if role == "branch_manager":
            return "manager"
        if role in {"cashier", "kitchen_staff"}:
            return "staff"
        if role == "admin":
            return (self.admin_tier or "owner").strip().lower() or "owner"
        return None

    def can_access_admin_tier(self, *tiers):
        from utils.permissions import admin_tier_meets

        return admin_tier_meets(self, *tiers)

    @property
    def is_employee_access_active(self):
        return (self.employee_status or "active").strip().lower() in {
            "active",
            "invited",
        }

    @property
    def loyalty_points(self):
        """Sum of non-expired active points in the ledger."""
        now = utcnow()
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
        if pts >= 1000:
            return "Gold"
        if pts >= 500:
            return "Silver"
        return "Bronze"

    def __repr__(self):
        return f"<User {self.email}>"


class LoginHistory(db.Model):
    __tablename__ = "login_history"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    login_time = db.Column(db.DateTime, default=utcnow)
    ip_address = db.Column(db.String(50))
    device     = db.Column(db.String(200))
    status     = db.Column(db.String(20), default="success")


class Subscription(db.Model):
    __tablename__ = "subscriptions"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"))
    plan = db.Column(db.String(20), default="monthly")
    discount_pct = db.Column(db.Numeric(5, 2), default=10)
    start_date = db.Column(db.DateTime, default=utcnow)
    end_date = db.Column(db.DateTime)
    next_billing_at = db.Column(db.DateTime)
    paused_until = db.Column(db.DateTime)
    status = db.Column(db.String(20), default="ACTIVE")
    is_active = db.Column(db.Boolean, default=True)
    price_paid = db.Column(db.Numeric(10, 2))
    recurrence = db.Column(db.String(20), default="monthly")
    delivery_window = db.Column(db.String(50))
    notes = db.Column(db.Text)
    items_json = db.Column(db.Text)

    branch = db.relationship("Branch", backref="subscriptions")
