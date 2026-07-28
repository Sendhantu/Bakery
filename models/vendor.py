from clock import utcnow
from .base import db


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
