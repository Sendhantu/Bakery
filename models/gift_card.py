import secrets
import string

from clock import utcnow
from .base import db


GIFT_CARD_STATUSES = ("active", "redeemed", "expired", "cancelled")
GIFT_CARD_TRANSACTION_TYPES = (
    "issued",
    "redeemed",
    "expired",
    "manual_adjustment",
)


def generate_gift_card_code():
    alphabet = string.ascii_uppercase + string.digits
    token = "".join(secrets.choice(alphabet) for _ in range(12))
    return f"SCGC-{token[:4]}-{token[4:8]}-{token[8:]}"


class GiftCard(db.Model):
    __tablename__ = "gift_cards"

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(40), unique=True, nullable=False)
    initial_value = db.Column(db.Numeric(10, 2), nullable=False)
    current_balance = db.Column(db.Numeric(10, 2), nullable=False)
    status = db.Column(db.String(20), default="active", nullable=False)
    purchased_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    recipient_email = db.Column(db.String(120))
    message = db.Column(db.Text)
    issued_at = db.Column(db.DateTime, default=utcnow, nullable=False)
    expires_at = db.Column(db.DateTime)

    purchaser = db.relationship("User", foreign_keys=[purchased_by_user_id])
    transactions = db.relationship(
        "GiftCardTransaction",
        backref="gift_card",
        lazy="dynamic",
        cascade="all, delete-orphan",
    )


class GiftCardTransaction(db.Model):
    __tablename__ = "gift_card_transactions"

    id = db.Column(db.Integer, primary_key=True)
    gift_card_id = db.Column(db.Integer, db.ForeignKey("gift_cards.id"), nullable=False)
    order_id = db.Column(db.Integer, db.ForeignKey("orders.id"))
    amount_change = db.Column(db.Numeric(10, 2), nullable=False)
    transaction_type = db.Column(db.String(30), nullable=False)
    reason = db.Column(db.Text)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)

    order = db.relationship("Order")
    creator = db.relationship("User", foreign_keys=[created_by])
