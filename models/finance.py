from clock import utcnow
from .encrypted_types import EncryptedDecimal, EncryptedText

from .base import db


class FinancialCategory(db.Model):
    __tablename__ = "financial_categories"

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(60), unique=True, nullable=False)
    label = db.Column(db.String(120), nullable=False)
    transaction_type = db.Column(db.String(20), nullable=False, default="expense")
    is_system = db.Column(db.Boolean, default=False, nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    sort_order = db.Column(db.Integer, default=0, nullable=False)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)

    transactions = db.relationship("FinancialTransaction", backref="category", lazy="dynamic")


class TaxRate(db.Model):
    __tablename__ = "tax_rates"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    code = db.Column(db.String(60), unique=True, nullable=False)
    rate_percent = db.Column(db.Numeric(6, 3), nullable=False)
    applies_to = db.Column(db.String(60))
    product_category_id = db.Column(db.Integer, db.ForeignKey("categories.id"))
    effective_from = db.Column(db.Date, nullable=False)
    effective_to = db.Column(db.Date)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)


class FinancialTransaction(db.Model):
    __tablename__ = "financial_transactions"

    id = db.Column(db.Integer, primary_key=True)
    transaction_type = db.Column(db.String(20), nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey("financial_categories.id"), nullable=False)
    amount = db.Column(EncryptedDecimal, nullable=False)
    tax_amount = db.Column(EncryptedDecimal)
    description = db.Column(EncryptedText)
    counterparty = db.Column(EncryptedText)
    reference_order_id = db.Column(db.Integer, db.ForeignKey("orders.id"))
    reference_stock_movement_id = db.Column(db.Integer, db.ForeignKey("stock_movements.id"))
    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"))
    store_location = db.Column(db.String(150))
    tds_withheld = db.Column(EncryptedDecimal)
    is_auto_generated = db.Column(db.Boolean, default=False, nullable=False)
    idempotency_key = db.Column(db.String(120), unique=True)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)

    order = db.relationship("Order", foreign_keys=[reference_order_id])
    stock_movement = db.relationship("StockMovement", foreign_keys=[reference_stock_movement_id])
    branch = db.relationship("Branch", foreign_keys=[branch_id])
    creator = db.relationship("User", foreign_keys=[created_by])

    __table_args__ = (
        db.Index("idx_fin_txn_type_created", "transaction_type", "created_at"),
        db.Index("idx_fin_txn_branch_created", "branch_id", "created_at"),
        db.Index("idx_fin_txn_order", "reference_order_id"),
        db.Index("idx_fin_txn_movement", "reference_stock_movement_id"),
    )


class TaxRecord(db.Model):
    __tablename__ = "tax_records"

    id = db.Column(db.Integer, primary_key=True)
    period_type = db.Column(db.String(20), nullable=False)
    period_start = db.Column(db.Date, nullable=False)
    period_end = db.Column(db.Date, nullable=False)
    gst_collected = db.Column(db.Numeric(12, 2), default=0, nullable=False)
    gst_paid = db.Column(db.Numeric(12, 2), default=0, nullable=False)
    net_gst_liability = db.Column(db.Numeric(12, 2), default=0, nullable=False)
    tds_withheld = db.Column(db.Numeric(12, 2), default=0, nullable=False)
    admin_adjustment_notes = db.Column(db.Text)
    computed_at = db.Column(db.DateTime, default=utcnow, nullable=False)

    __table_args__ = (
        db.UniqueConstraint("period_type", "period_start", "period_end", name="uq_tax_record_period"),
    )
