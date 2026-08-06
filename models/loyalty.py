from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_CEILING, ROUND_FLOOR

from clock import utcnow
from flask import current_app, has_app_context
from .base import db

# ─────────────────────────────────────────
# LOYALTY CONSTANTS
# ─────────────────────────────────────────
LOYALTY_EARN_RATE = 1  # 1 point per ₹10 spent
LOYALTY_EARN_PER = 10  # ₹10 = 1 point
LOYALTY_REDEEM_RATE = 10  # 10 points = ₹10 off
LOYALTY_REDEEM_PER = 10  # redeem only in 10-point chunks
LOYALTY_REDEEM_MAX_PERCENT = 20
LOYALTY_MIN_REDEEM_ORDER_VALUE = 500
LOYALTY_MIN_REDEEM_PERCENT = 10
LOYALTY_POINTS_TTL_DAYS = 365  # points expire after 1 year


def get_loyalty_config():
    defaults = {
        "LOYALTY_EARN_RATE": LOYALTY_EARN_RATE,
        "LOYALTY_EARN_PER": LOYALTY_EARN_PER,
        "LOYALTY_REDEEM_RATE": LOYALTY_REDEEM_RATE,
        "LOYALTY_REDEEM_PER": LOYALTY_REDEEM_PER,
        "LOYALTY_REDEEM_MAX_PERCENT": LOYALTY_REDEEM_MAX_PERCENT,
        "LOYALTY_MIN_REDEEM_ORDER_VALUE": LOYALTY_MIN_REDEEM_ORDER_VALUE,
        "LOYALTY_MIN_REDEEM_PERCENT": LOYALTY_MIN_REDEEM_PERCENT,
        "LOYALTY_EXPIRY_DAYS": LOYALTY_POINTS_TTL_DAYS,
    }
    if not has_app_context():
        return defaults

    resolved = {}
    for key, fallback in defaults.items():
        try:
            resolved[key] = int(current_app.config.get(key, fallback))
        except (TypeError, ValueError):
            resolved[key] = fallback
    return resolved


def calculate_loyalty_redemption(points_requested, subtotal, available_points=None):
    loyalty = get_loyalty_config()
    redeem_per = max(1, loyalty["LOYALTY_REDEEM_PER"])
    redeem_rate = max(1, loyalty["LOYALTY_REDEEM_RATE"])
    max_percent = max(0, loyalty["LOYALTY_REDEEM_MAX_PERCENT"])
    min_order_value = max(0, loyalty["LOYALTY_MIN_REDEEM_ORDER_VALUE"])
    min_percent = max(0, loyalty["LOYALTY_MIN_REDEEM_PERCENT"])

    try:
        points_requested = int(points_requested or 0)
    except (TypeError, ValueError):
        points_requested = 0

    normalized_points = max(0, points_requested)
    if available_points is not None:
        normalized_points = min(normalized_points, max(0, int(available_points)))
    normalized_points -= normalized_points % redeem_per

    try:
        subtotal_value = Decimal(str(subtotal or 0))
    except (InvalidOperation, TypeError, ValueError):
        subtotal_value = Decimal("0")

    subtotal_value = max(subtotal_value, Decimal("0"))
    redeem_rate_value = Decimal(str(redeem_rate))
    max_allowed_discount = (
        subtotal_value * Decimal(str(max_percent)) / Decimal("100")
    ).quantize(Decimal("0.01"))
    max_discount_units = int(
        (max_allowed_discount / redeem_rate_value).to_integral_value(
            rounding=ROUND_FLOOR
        )
    )

    max_points_by_cap = max_discount_units * redeem_per
    min_required_discount = Decimal("0")
    min_points_required = 0
    below_minimum = False

    if normalized_points > 0 and subtotal_value > Decimal(str(min_order_value)):
        min_required_discount = (
            subtotal_value * Decimal(str(min_percent)) / Decimal("100")
        ).quantize(Decimal("0.01"))
        min_discount_units = int(
            (min_required_discount / redeem_rate_value).to_integral_value(
                rounding=ROUND_CEILING
            )
        )
        min_points_required = min_discount_units * redeem_per
        below_minimum = normalized_points < min_points_required

    points_applied = 0 if below_minimum else min(normalized_points, max_points_by_cap)
    discount = Decimal(points_applied // redeem_per) * redeem_rate_value

    return {
        "points_requested": normalized_points,
        "points_applied": points_applied,
        "discount": round(float(discount), 2),
        "requested_discount": round(
            float(Decimal(normalized_points // redeem_per) * redeem_rate_value),
            2,
        ),
        "max_allowed_discount": round(float(max_allowed_discount), 2),
        "min_required_discount": round(float(min_required_discount), 2),
        "min_points_required": min_points_required,
        "below_minimum": below_minimum,
        "capped": points_applied < normalized_points,
        "redeem_per": redeem_per,
        "redeem_rate": redeem_rate,
        "max_percent": max_percent,
        "min_order_value": min_order_value,
        "min_percent": min_percent,
    }


class LoyaltyLedger(db.Model):
    __tablename__ = "loyalty_ledger"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    order_id = db.Column(db.Integer, db.ForeignKey("orders.id"), nullable=True)
    points = db.Column(db.Integer, nullable=False)  # +earn / -redeem
    reason = db.Column(
        db.String(100), nullable=False
    )  # 'order_earned', 'redeemed', 'admin_adj', 'expired'
    created_at = db.Column(db.DateTime, default=utcnow)
    expires_at = db.Column(db.DateTime, nullable=True)

    __table_args__ = (db.Index("idx_loyalty_user", "user_id"),)

    @classmethod
    def earn(cls, user_id, order_id, order_total):
        """Award points for a completed order."""
        loyalty = get_loyalty_config()
        earn_per = max(1, loyalty["LOYALTY_EARN_PER"])
        earn_rate = max(1, loyalty["LOYALTY_EARN_RATE"])
        expiry_days = max(1, loyalty["LOYALTY_EXPIRY_DAYS"])

        pts = int(float(order_total) // earn_per) * earn_rate
        if pts <= 0:
            return 0
        entry = cls(
            user_id=user_id,
            order_id=order_id,
            points=pts,
            reason="order_earned",
            expires_at=utcnow() + timedelta(days=expiry_days),
        )
        db.session.add(entry)
        return pts

    @classmethod
    def redeem(cls, user_id, order_id, points_to_redeem):
        """Deduct points at redemption. Returns ₹ discount or raises ValueError."""
        loyalty = get_loyalty_config()
        redeem_per = max(1, loyalty["LOYALTY_REDEEM_PER"])
        redeem_rate = max(1, loyalty["LOYALTY_REDEEM_RATE"])

        if points_to_redeem < redeem_per:
            raise ValueError(f"Minimum {redeem_per} points required to redeem.")

        from .user import User

        user = db.session.get(User, user_id)
        if user is None:
            raise ValueError("User not found.")
        if user.loyalty_points < points_to_redeem:
            raise ValueError("Not enough loyalty points.")

        discount = (points_to_redeem // redeem_per) * redeem_rate
        entry = cls(
            user_id=user_id,
            order_id=order_id,
            points=-points_to_redeem,
            reason="redeemed",
        )
        db.session.add(entry)
        return discount

    @classmethod
    def admin_adjust(cls, user_id, points, reason="admin_adj"):
        entry = cls(user_id=user_id, points=points, reason=reason)
        db.session.add(entry)
        return entry
