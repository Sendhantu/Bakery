from decimal import Decimal

from clock import utcnow
from .base import db


TDS_PAYMENT_TYPE_NONE = "none"
TDS_PAYMENT_TYPE_GOODS = "goods"
TDS_PAYMENT_TYPE_RENT = "rent"
TDS_PAYMENT_TYPE_CONTRACT_INDIVIDUAL = "contract_individual"
TDS_PAYMENT_TYPE_CONTRACT_COMPANY = "contract_company"
TDS_PAYMENT_TYPE_PROFESSIONAL_2 = "professional_2"
TDS_PAYMENT_TYPE_PROFESSIONAL_10 = "professional_10"

TDS_PAYMENT_TYPE_CHOICES = [
    (TDS_PAYMENT_TYPE_NONE, "No TDS / not applicable"),
    (TDS_PAYMENT_TYPE_GOODS, "Raw materials / goods - Section 194Q"),
    (TDS_PAYMENT_TYPE_RENT, "Commercial rent - Section 194I"),
    (
        TDS_PAYMENT_TYPE_CONTRACT_INDIVIDUAL,
        "Contracts/job work - Section 194C at 1%",
    ),
    (
        TDS_PAYMENT_TYPE_CONTRACT_COMPANY,
        "Contracts/job work - Section 194C at 2%",
    ),
    (
        TDS_PAYMENT_TYPE_PROFESSIONAL_2,
        "Professional/technical fees - Section 194J at 2%",
    ),
    (
        TDS_PAYMENT_TYPE_PROFESSIONAL_10,
        "Professional fees - Section 194J at 10%",
    ),
]
TDS_PAYMENT_TYPE_LABELS = dict(TDS_PAYMENT_TYPE_CHOICES)
TDS_PAYMENT_TYPE_VALUES = {value for value, _label in TDS_PAYMENT_TYPE_CHOICES}

TDS_PAYMENT_TYPE_CONFIG = {
    TDS_PAYMENT_TYPE_NONE: {
        "section": "",
        "rate": Decimal("0"),
        "annual_threshold": Decimal("0"),
        "single_threshold": None,
        "gate_note": "TDS is disabled for this vendor.",
    },
    TDS_PAYMENT_TYPE_GOODS: {
        "section": "194Q",
        "rate": Decimal("0.10"),
        "annual_threshold": Decimal("5000000"),
        "single_threshold": None,
        "gate_note": "Use only if previous financial-year turnover crossed Rs. 10 crore.",
    },
    TDS_PAYMENT_TYPE_RENT: {
        "section": "194I",
        "rate": Decimal("10"),
        "annual_threshold": Decimal("2400000"),
        "single_threshold": None,
        "gate_note": "Use for commercial shop or facility rent.",
    },
    TDS_PAYMENT_TYPE_CONTRACT_INDIVIDUAL: {
        "section": "194C",
        "rate": Decimal("1"),
        "annual_threshold": Decimal("100000"),
        "single_threshold": Decimal("30000"),
        "gate_note": "Use when contractor payee is an individual or HUF.",
    },
    TDS_PAYMENT_TYPE_CONTRACT_COMPANY: {
        "section": "194C",
        "rate": Decimal("2"),
        "annual_threshold": Decimal("100000"),
        "single_threshold": Decimal("30000"),
        "gate_note": "Use when contractor payee is a firm or company.",
    },
    TDS_PAYMENT_TYPE_PROFESSIONAL_2: {
        "section": "194J",
        "rate": Decimal("2"),
        "annual_threshold": Decimal("30000"),
        "single_threshold": None,
        "gate_note": "Use for eligible technical or specified professional fees.",
    },
    TDS_PAYMENT_TYPE_PROFESSIONAL_10: {
        "section": "194J",
        "rate": Decimal("10"),
        "annual_threshold": Decimal("30000"),
        "single_threshold": None,
        "gate_note": "Use for professional fees where the 10% rate applies.",
    },
}
TDS_NO_PAN_RATE = Decimal("20")


class Vendor(db.Model):
    __tablename__ = "vendors"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False, unique=True)
    contact_person = db.Column(db.String(120))
    phone = db.Column(db.String(30))
    email = db.Column(db.String(120))
    address = db.Column(db.Text)
    payment_terms = db.Column(db.String(120))
    gstin = db.Column(db.String(20))
    pan = db.Column(db.String(20))
    tds_enabled = db.Column(db.Boolean, default=False, nullable=False)
    tds_payment_type = db.Column(
        db.String(40), default=TDS_PAYMENT_TYPE_NONE, nullable=False
    )
    tds_rate_percent = db.Column(db.Numeric(6, 3))
    tds_threshold_amount = db.Column(db.Numeric(12, 2))
    tds_notes = db.Column(db.Text)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)

    products = db.relationship("VendorProduct", backref="vendor", lazy="dynamic")
    purchase_orders = db.relationship("PurchaseOrder", backref="vendor", lazy="dynamic")

    @property
    def gst_registered(self):
        return bool((self.gstin or "").strip())

    @property
    def input_tax_credit_eligible(self):
        return self.gst_registered

    @property
    def tds_payment_type_label(self):
        return TDS_PAYMENT_TYPE_LABELS.get(
            self.tds_payment_type or TDS_PAYMENT_TYPE_NONE,
            TDS_PAYMENT_TYPE_LABELS[TDS_PAYMENT_TYPE_NONE],
        )

    @property
    def tds_config(self):
        return TDS_PAYMENT_TYPE_CONFIG.get(
            self.tds_payment_type or TDS_PAYMENT_TYPE_NONE,
            TDS_PAYMENT_TYPE_CONFIG[TDS_PAYMENT_TYPE_NONE],
        )

    @property
    def tds_section(self):
        return self.tds_config["section"]

    @property
    def effective_tds_rate_percent(self):
        if self.tds_rate_percent is not None:
            return Decimal(str(self.tds_rate_percent))
        return self.tds_config["rate"]

    @property
    def effective_tds_annual_threshold(self):
        if self.tds_threshold_amount is not None:
            return Decimal(str(self.tds_threshold_amount))
        return self.tds_config["annual_threshold"]

    @property
    def pan_on_file(self):
        return bool((self.pan or "").strip())


class VendorProduct(db.Model):
    __tablename__ = "vendor_products"

    id = db.Column(db.Integer, primary_key=True)
    vendor_id = db.Column(db.Integer, db.ForeignKey("vendors.id"), nullable=False)
    raw_material_id = db.Column(
        db.Integer, db.ForeignKey("raw_materials.id"), nullable=False
    )
    typical_unit_cost = db.Column(db.Numeric(10, 2))
    last_unit_cost = db.Column(db.Numeric(10, 2))
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    raw_material = db.relationship(
        "RawMaterial", backref=db.backref("vendor_products", lazy="dynamic")
    )

    __table_args__ = (
        db.UniqueConstraint(
            "vendor_id", "raw_material_id", name="uq_vendor_raw_material"
        ),
        db.Index("idx_vendor_product_vendor", "vendor_id"),
        db.Index("idx_vendor_product_material", "raw_material_id"),
    )


class PurchaseOrder(db.Model):
    __tablename__ = "purchase_orders"

    id = db.Column(db.Integer, primary_key=True)
    vendor_id = db.Column(db.Integer, db.ForeignKey("vendors.id"), nullable=False)
    status = db.Column(db.String(30), default="draft", nullable=False)
    order_date = db.Column(db.Date, default=lambda: utcnow().date(), nullable=False)
    expected_delivery_date = db.Column(db.Date)
    received_at = db.Column(db.DateTime)
    notes = db.Column(db.Text)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    gst_rate_percent = db.Column(db.Numeric(6, 3), default=0, nullable=False)
    tds_applicable = db.Column(db.Boolean, default=False, nullable=False)
    tds_section = db.Column(db.String(20))
    tds_rate_percent = db.Column(db.Numeric(6, 3), default=0, nullable=False)
    tds_base_amount = db.Column(db.Numeric(12, 2), default=0, nullable=False)
    tds_amount = db.Column(db.Numeric(12, 2), default=0, nullable=False)
    tds_reason = db.Column(db.String(255))
    tds_deducted_at = db.Column(db.DateTime)
    tds_deposit_due_date = db.Column(db.Date)
    tds_deposited_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)

    items = db.relationship(
        "PurchaseOrderItem",
        backref="purchase_order",
        lazy="dynamic",
        cascade="all, delete-orphan",
    )
    creator = db.relationship("User", foreign_keys=[created_by])

    __table_args__ = (
        db.Index("idx_purchase_order_vendor", "vendor_id"),
        db.Index("idx_purchase_order_status", "status"),
        db.Index("idx_purchase_order_order_date", "order_date"),
    )

    @property
    def subtotal(self):
        return sum(item.line_total for item in self.items.all())

    @property
    def input_tax_credit_eligible(self):
        return bool(self.vendor and self.vendor.input_tax_credit_eligible)

    @property
    def tds_pending_deposit(self):
        return bool(
            self.tds_amount
            and Decimal(str(self.tds_amount)) > 0
            and not self.tds_deposited_at
        )


class PurchaseOrderItem(db.Model):
    __tablename__ = "purchase_order_items"

    id = db.Column(db.Integer, primary_key=True)
    purchase_order_id = db.Column(
        db.Integer,
        db.ForeignKey("purchase_orders.id"),
        nullable=False,
    )
    raw_material_id = db.Column(
        db.Integer, db.ForeignKey("raw_materials.id"), nullable=False
    )
    quantity = db.Column(db.Numeric(10, 2), nullable=False)
    unit_cost = db.Column(db.Numeric(10, 2), nullable=False)

    raw_material = db.relationship("RawMaterial")

    __table_args__ = (
        db.Index("idx_purchase_order_item_order", "purchase_order_id"),
        db.Index("idx_purchase_order_item_material", "raw_material_id"),
    )

    @property
    def line_total(self):
        return (self.quantity or 0) * (self.unit_cost or 0)
