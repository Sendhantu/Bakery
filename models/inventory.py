from datetime import date, datetime
import uuid
from decimal import Decimal

from clock import utcnow
from .base import db


STOCK_MOVEMENT_REASONS = [
    ("manual_restock", "Manual restock"),
    ("purchase_order_received", "Purchase received"),
    ("order_deduction", "Order deduction"),
    ("usage", "Usage"),
    ("wastage", "Wastage"),
    ("damage", "Damage"),
    ("expired", "Expired stock"),
    ("return_to_supplier", "Returned to supplier"),
    ("correction", "Stock correction"),
]
STOCK_MOVEMENT_REASON_LABELS = dict(STOCK_MOVEMENT_REASONS)

STOCK_TRANSFER_STATUSES = [
    ("PREPARED", "Prepared"),
    ("DISPATCHED", "Dispatched"),
    ("IN_TRANSIT", "In transit"),
    ("RECEIVED", "Received"),
    ("CANCELLED", "Cancelled"),
]
STOCK_TRANSFER_STATUS_LABELS = dict(STOCK_TRANSFER_STATUSES)
STOCK_TRANSFER_STATUS_VALUES = {value for value, _label in STOCK_TRANSFER_STATUSES}

PURCHASE_REQUEST_STATUSES = [
    ("DRAFT", "Draft"),
    ("SUBMITTED", "Submitted"),
    ("UNDER_REVIEW", "Under review"),
    ("APPROVED", "Approved"),
    ("PARTIALLY_APPROVED", "Partially approved"),
    ("REJECTED", "Rejected"),
    ("FULFILLED", "Fulfilled"),
    ("CANCELLED", "Cancelled"),
]
PURCHASE_REQUEST_STATUS_LABELS = dict(PURCHASE_REQUEST_STATUSES)
PURCHASE_REQUEST_STATUS_VALUES = {value for value, _label in PURCHASE_REQUEST_STATUSES}

BATCH_STATUSES = [
    ("available", "Available"),
    ("partially_used", "Partially Used"),
    ("fully_used", "Fully Used"),
    ("expired", "Expired"),
    ("damaged", "Damaged"),
    ("returned", "Returned"),
    ("blocked", "Blocked"),
]
BATCH_STATUS_LABELS = dict(BATCH_STATUSES)
BATCH_CONSUMABLE_STATUSES = {"available", "partially_used"}
BATCH_UNUSABLE_STATUSES = {"expired", "damaged", "returned", "blocked"}

MATERIAL_DOCUMENT_TYPES = [
    ("supplier_invoice", "Supplier Invoice"),
    ("purchase_bill", "Purchase Bill"),
    ("delivery_receipt", "Delivery Receipt"),
    ("quality_certificate", "Quality Certificate"),
    ("payment_receipt", "Payment Receipt"),
    ("product_image", "Product Image"),
    ("other", "Other"),
]
MATERIAL_DOCUMENT_TYPE_LABELS = dict(MATERIAL_DOCUMENT_TYPES)
MATERIAL_DOCUMENT_TYPE_VALUES = {value for value, _label in MATERIAL_DOCUMENT_TYPES}


class RawMaterial(db.Model):
    __tablename__ = 'raw_materials'
    id            = db.Column(db.Integer, primary_key=True)
    name          = db.Column(db.String(120), nullable=False, unique=True)
    sku           = db.Column(db.String(60))
    category      = db.Column(db.String(80))
    branch_id     = db.Column(db.Integer, db.ForeignKey('branches.id'))
    unit          = db.Column(db.String(30), nullable=False, default='kg')
    stock         = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    reserved_quantity = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    reorder_level = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    min_stock     = db.Column(db.Numeric(10, 2), default=0)
    max_stock     = db.Column(db.Numeric(10, 2))
    cost_per_unit = db.Column(db.Numeric(10, 2), default=0)
    supplier      = db.Column(db.String(120))
    preferred_supplier_id = db.Column(db.Integer, db.ForeignKey('vendors.id'))
    storage_location = db.Column(db.String(150))
    shelf_life_days = db.Column(db.Integer)
    tax_rate_percent = db.Column(db.Numeric(6, 3), default=0)
    expiring_soon_days = db.Column(db.Integer, default=14, nullable=False)
    last_purchased_at = db.Column(db.DateTime)
    last_purchase_quantity = db.Column(db.Numeric(10, 2))
    last_purchase_unit_price = db.Column(db.Numeric(10, 2))
    notes         = db.Column(db.Text)
    is_active     = db.Column(db.Boolean, default=True)
    version       = db.Column(db.Integer, default=1, nullable=False)
    updated_by    = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at    = db.Column(db.DateTime, default=utcnow)
    updated_at    = db.Column(db.DateTime, default=utcnow, onupdate=utcnow)
    recipe_items  = db.relationship('ProductMaterial', backref='raw_material', lazy='dynamic')
    stock_movements = db.relationship('StockMovement', backref='raw_material', lazy='dynamic')
    batches       = db.relationship('MaterialBatch', backref='raw_material', lazy='dynamic')
    documents     = db.relationship('MaterialDocument', backref='raw_material', lazy='dynamic')

    branch = db.relationship('Branch', backref='raw_materials')
    preferred_supplier = db.relationship('Vendor', foreign_keys=[preferred_supplier_id])
    updater = db.relationship('User', foreign_keys=[updated_by])

    __table_args__ = (
        db.Index('idx_raw_material_branch', 'branch_id'),
        db.Index('idx_raw_material_active', 'is_active'),
        db.Index('idx_raw_material_category', 'category'),
        db.Index('idx_raw_material_supplier', 'preferred_supplier_id'),
    )

    @property
    def stock_status(self):
        stock = float(self.stock or 0)
        reorder = float(self.reorder_level or 0)
        if stock <= 0:
            return 'out_of_stock'
        if reorder > 0 and stock <= reorder:
            return 'low_stock'
        return 'in_stock'

    @property
    def reorder_required(self):
        reorder = Decimal(str(self.reorder_level or 0))
        return reorder > 0 and Decimal(str(self.stock or 0)) <= reorder

    @property
    def usable_quantity(self):
        return max(Decimal("0"), Decimal(str(self.stock or 0)) - Decimal(str(self.reserved_quantity or 0)))

    @property
    def inventory_value(self):
        return Decimal(str(self.stock or 0)) * Decimal(str(self.cost_per_unit or 0))

    @property
    def expiry_summary(self):
        if self.batches is None:
            return {"status": "none", "nearest": None}
        expiring_soon_days = int(self.expiring_soon_days or 14)
        nearest = None
        has_unusable = False
        for batch in self.batches:
            if batch.expiry_date is None or batch.status in BATCH_UNUSABLE_STATUSES or Decimal(str(batch.remaining_quantity or 0)) <= 0:
                continue
            days_left = (batch.expiry_date - utcnow().date()).days
            if days_left < 0:
                has_unusable = True
                continue
            if nearest is None or batch.expiry_date < nearest:
                nearest = batch.expiry_date
        if nearest is None:
            return {"status": "expired" if has_unusable else "none", "nearest": None}
        days_left = (nearest - utcnow().date()).days
        if days_left <= expiring_soon_days:
            return {"status": "expiring_soon", "nearest": nearest}
        return {"status": "ok", "nearest": nearest}


class MaterialBatch(db.Model):
    __tablename__ = 'material_batches'
    id                = db.Column(db.Integer, primary_key=True)
    raw_material_id   = db.Column(db.Integer, db.ForeignKey('raw_materials.id'), nullable=False)
    batch_number      = db.Column(db.String(120), nullable=False)
    supplier_id       = db.Column(db.Integer, db.ForeignKey('vendors.id'))
    purchase_order_id = db.Column(db.Integer, db.ForeignKey('purchase_orders.id'))
    received_quantity = db.Column(db.Numeric(10, 2), nullable=False)
    remaining_quantity = db.Column(db.Numeric(10, 2), nullable=False)
    unit_cost         = db.Column(db.Numeric(10, 2))
    manufacturing_date = db.Column(db.Date)
    expiry_date       = db.Column(db.Date)
    storage_location  = db.Column(db.String(150))
    status            = db.Column(db.String(30), default='available', nullable=False)
    notes             = db.Column(db.Text)
    created_by        = db.Column(db.Integer, db.ForeignKey('users.id'))
    received_at       = db.Column(db.DateTime, default=utcnow)
    created_at        = db.Column(db.DateTime, default=utcnow)
    updated_at        = db.Column(db.DateTime, default=utcnow, onupdate=utcnow)

    supplier = db.relationship('Vendor')
    purchase_order = db.relationship('PurchaseOrder')
    creator = db.relationship('User', foreign_keys=[created_by])

    __table_args__ = (
        db.Index('idx_material_batch_material_status', 'raw_material_id', 'status'),
        db.Index('idx_material_batch_expiry', 'expiry_date'),
        db.Index('idx_material_batch_po', 'purchase_order_id'),
    )

    @property
    def usable_quantity(self):
        if self.status in BATCH_UNUSABLE_STATUSES:
            return Decimal("0")
        return Decimal(str(self.remaining_quantity or 0))

    @property
    def expiry_status(self):
        if not self.expiry_date:
            return "none"
        days_left = (self.expiry_date - utcnow().date()).days
        if days_left < 0:
            return "expired"
        threshold = int((self.raw_material.expiring_soon_days if self.raw_material else 14) or 14)
        if days_left <= threshold:
            return "expiring_soon"
        return "ok"

    @property
    def days_to_expiry(self):
        if not self.expiry_date:
            return None
        return (self.expiry_date - utcnow().date()).days


class MaterialDocument(db.Model):
    __tablename__ = 'material_documents'
    id                = db.Column(db.Integer, primary_key=True)
    raw_material_id   = db.Column(db.Integer, db.ForeignKey('raw_materials.id'), nullable=False)
    purchase_order_id = db.Column(db.Integer, db.ForeignKey('purchase_orders.id'))
    doc_type          = db.Column(db.String(40), nullable=False)
    original_filename = db.Column(db.String(255), nullable=False)
    stored_path       = db.Column(db.String(500), nullable=False)
    size_bytes        = db.Column(db.Integer, default=0)
    uploaded_by       = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at        = db.Column(db.DateTime, default=utcnow, nullable=False)

    purchase_order = db.relationship('PurchaseOrder')
    uploader = db.relationship('User', foreign_keys=[uploaded_by])

    __table_args__ = (
        db.Index('idx_material_doc_material', 'raw_material_id'),
        db.Index('idx_material_doc_po', 'purchase_order_id'),
    )


class ProductMaterial(db.Model):
    __tablename__ = 'product_materials'
    id                = db.Column(db.Integer, primary_key=True)
    product_id        = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    raw_material_id   = db.Column(db.Integer, db.ForeignKey('raw_materials.id'), nullable=False)
    quantity_required = db.Column(db.Numeric(10, 2), nullable=False, default=0)

    __table_args__ = (
        db.UniqueConstraint('product_id', 'raw_material_id', name='uq_product_material'),
    )


class StockMovement(db.Model):
    __tablename__ = 'stock_movements'
    id = db.Column(db.Integer, primary_key=True)
    raw_material_id = db.Column(db.Integer, db.ForeignKey('raw_materials.id'), nullable=False)
    change_amount = db.Column(db.Numeric(10, 2), nullable=False)
    stock_after = db.Column(db.Numeric(10, 2), nullable=False)
    reason = db.Column(db.String(40), nullable=False)
    notes = db.Column(db.Text)
    reference_order_id = db.Column(db.Integer, db.ForeignKey('orders.id'))
    reference_purchase_order_id = db.Column(db.Integer, db.ForeignKey('purchase_orders.id'))
    reference_batch_id = db.Column(db.Integer, db.ForeignKey('material_batches.id'))
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)

    reference_order = db.relationship('Order', backref='stock_movements')
    reference_purchase_order = db.relationship('PurchaseOrder')
    reference_batch = db.relationship('MaterialBatch')
    actor = db.relationship('User', backref='stock_movements')

    __table_args__ = (
        db.Index('idx_stock_movement_material_created', 'raw_material_id', 'created_at'),
        db.Index('idx_stock_movement_order', 'reference_order_id'),
        db.Index('idx_stock_movement_reason', 'reason'),
        db.Index('idx_stock_movement_po', 'reference_purchase_order_id'),
        db.Index('idx_stock_movement_batch', 'reference_batch_id'),
    )


class Supplier(db.Model):
    __tablename__ = 'suppliers'
    id            = db.Column(db.Integer, primary_key=True)
    name          = db.Column(db.String(150), nullable=False, unique=True)
    contact_name  = db.Column(db.String(120))
    email         = db.Column(db.String(120))
    phone         = db.Column(db.String(30))
    address       = db.Column(db.Text)
    payment_terms = db.Column(db.String(200))
    notes         = db.Column(db.Text)
    is_active     = db.Column(db.Boolean, default=True)
    created_at    = db.Column(db.DateTime, default=utcnow)

    @property
    def status(self):
        return 'Active' if self.is_active else 'Paused'


class Branch(db.Model):
    __tablename__ = 'branches'
    id           = db.Column(db.Integer, primary_key=True)
    name         = db.Column(db.String(150), nullable=False, unique=True)
    manager_name = db.Column(db.String(120))
    phone        = db.Column(db.String(30))
    address      = db.Column(db.Text)
    is_active    = db.Column(db.Boolean, default=True)
    created_at   = db.Column(db.DateTime, default=utcnow)

    @property
    def status(self):
        return 'Open' if self.is_active else 'Closed'


class BranchProductAssignment(db.Model):
    __tablename__ = "branch_product_assignments"
    id = db.Column(db.Integer, primary_key=True)
    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=False)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)

    branch = db.relationship("Branch", backref="product_assignments")
    product = db.relationship("Product", backref="branch_assignments")
    creator = db.relationship("User")

    __table_args__ = (
        db.UniqueConstraint("branch_id", "product_id", name="uq_branch_product_assignment"),
        db.Index("idx_branch_product_assignment_active", "branch_id", "is_active"),
    )


class BranchInventory(db.Model):
    __tablename__ = "branch_inventory"
    id = db.Column(db.Integer, primary_key=True)
    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"))
    raw_material_id = db.Column(db.Integer, db.ForeignKey("raw_materials.id"))
    quantity = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    reserved_quantity = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    min_stock = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    sync_status = db.Column(db.String(30), nullable=False, default="SYNCED")
    version = db.Column(db.Integer, nullable=False, default=1)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    branch = db.relationship("Branch", backref="inventory_items")
    product = db.relationship("Product", backref="branch_inventory_items")
    raw_material = db.relationship("RawMaterial", backref="branch_inventory_items")

    __table_args__ = (
        db.UniqueConstraint("branch_id", "product_id", name="uq_branch_inventory_product"),
        db.UniqueConstraint("branch_id", "raw_material_id", name="uq_branch_inventory_material"),
        db.Index("idx_branch_inventory_branch_status", "branch_id", "sync_status"),
    )

    @property
    def available_quantity(self):
        return max(
            Decimal("0"),
            Decimal(str(self.quantity or 0)) - Decimal(str(self.reserved_quantity or 0)),
        )

    @property
    def is_low_stock(self):
        return Decimal(str(self.min_stock or 0)) > 0 and self.available_quantity <= Decimal(str(self.min_stock or 0))


class StockTransfer(db.Model):
    __tablename__ = "stock_transfers"
    id = db.Column(db.Integer, primary_key=True)
    transfer_number = db.Column(
        db.String(80),
        nullable=False,
        unique=True,
        default=lambda: f"TRF-{uuid.uuid4().hex[:10].upper()}",
    )
    source_location = db.Column(db.String(80), nullable=False, default="CENTRAL_KITCHEN")
    destination_branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"), nullable=False)
    status = db.Column(db.String(30), nullable=False, default="PREPARED")
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    received_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    prepared_at = db.Column(db.DateTime, default=utcnow, nullable=False)
    dispatched_at = db.Column(db.DateTime)
    received_at = db.Column(db.DateTime)
    idempotency_key = db.Column(db.String(120), unique=True)
    sync_status = db.Column(db.String(30), nullable=False, default="SYNCED")
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow)

    destination_branch = db.relationship("Branch", backref="incoming_stock_transfers")
    creator = db.relationship("User", foreign_keys=[created_by])
    receiver = db.relationship("User", foreign_keys=[received_by])
    items = db.relationship("StockTransferItem", backref="transfer", lazy="dynamic", cascade="all, delete-orphan")

    __table_args__ = (
        db.Index("idx_stock_transfer_branch_status", "destination_branch_id", "status"),
        db.Index("idx_stock_transfer_sync", "sync_status", "updated_at"),
    )


class StockTransferItem(db.Model):
    __tablename__ = "stock_transfer_items"
    id = db.Column(db.Integer, primary_key=True)
    transfer_id = db.Column(db.Integer, db.ForeignKey("stock_transfers.id"), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"))
    raw_material_id = db.Column(db.Integer, db.ForeignKey("raw_materials.id"))
    quantity = db.Column(db.Numeric(10, 2), nullable=False)
    received_quantity = db.Column(db.Numeric(10, 2), nullable=False, default=0)

    product = db.relationship("Product")
    raw_material = db.relationship("RawMaterial")

    __table_args__ = (
        db.Index("idx_stock_transfer_item_transfer", "transfer_id"),
    )


class BranchPurchaseRequest(db.Model):
    __tablename__ = "branch_purchase_requests"
    id = db.Column(db.Integer, primary_key=True)
    request_number = db.Column(
        db.String(80),
        nullable=False,
        unique=True,
        default=lambda: f"PRQ-{uuid.uuid4().hex[:10].upper()}",
    )
    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"), nullable=False)
    requested_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    priority = db.Column(db.String(20), nullable=False, default="normal")
    reason = db.Column(db.Text)
    status = db.Column(db.String(30), nullable=False, default="DRAFT")
    admin_response = db.Column(db.Text)
    sync_status = db.Column(db.String(30), nullable=False, default="SYNCED")
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=utcnow, onupdate=utcnow)
    submitted_at = db.Column(db.DateTime)
    reviewed_at = db.Column(db.DateTime)
    reviewed_by = db.Column(db.Integer, db.ForeignKey("users.id"))

    branch = db.relationship("Branch", backref="purchase_requests")
    requester = db.relationship("User", foreign_keys=[requested_by])
    reviewer = db.relationship("User", foreign_keys=[reviewed_by])
    items = db.relationship("BranchPurchaseRequestItem", backref="request", lazy="dynamic", cascade="all, delete-orphan")

    __table_args__ = (
        db.Index("idx_branch_purchase_request_branch_status", "branch_id", "status"),
        db.Index("idx_branch_purchase_request_sync", "sync_status", "updated_at"),
    )


class BranchPurchaseRequestItem(db.Model):
    __tablename__ = "branch_purchase_request_items"
    id = db.Column(db.Integer, primary_key=True)
    request_id = db.Column(db.Integer, db.ForeignKey("branch_purchase_requests.id"), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"))
    raw_material_id = db.Column(db.Integer, db.ForeignKey("raw_materials.id"))
    requested_quantity = db.Column(db.Numeric(10, 2), nullable=False)
    approved_quantity = db.Column(db.Numeric(10, 2))
    notes = db.Column(db.Text)

    product = db.relationship("Product")
    raw_material = db.relationship("RawMaterial")

    __table_args__ = (
        db.Index("idx_branch_purchase_request_item_request", "request_id"),
    )


class ProductionPlan(db.Model):
    __tablename__ = 'production_plans'
    id             = db.Column(db.Integer, primary_key=True)
    product_id     = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    branch_id      = db.Column(db.Integer, db.ForeignKey('branches.id'))
    planned_date   = db.Column(db.DateTime, nullable=False)
    quantity       = db.Column(db.Integer, nullable=False, default=0)
    status         = db.Column(db.String(30), default='Scheduled')
    forecast_quantity = db.Column(db.Integer, default=0)
    estimated_prep_minutes = db.Column(db.Integer, default=0)
    staff_hours_estimate = db.Column(db.Numeric(10, 2), default=0)
    oven_slot = db.Column(db.String(50))
    priority = db.Column(db.String(20), default='normal')
    notes          = db.Column(db.Text)
    created_at     = db.Column(db.DateTime, default=utcnow)

    product = db.relationship('Product', backref='production_plans')
    branch  = db.relationship('Branch', backref='production_plans')

    @property
    def summary(self):
        return f'{self.quantity} units on {self.planned_date.strftime("%d %b %Y")}'


class ProductionBatch(db.Model):
    __tablename__ = 'production_batches'
    id               = db.Column(db.Integer, primary_key=True)
    batch_code       = db.Column(db.String(120), nullable=False, unique=True, default=lambda: f"BATCH-{uuid.uuid4().hex[:8].upper()}")
    product_id       = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    branch_id        = db.Column(db.Integer, db.ForeignKey('branches.id'))
    produced_at      = db.Column(db.DateTime, default=utcnow)
    expiry_date      = db.Column(db.DateTime)
    quantity         = db.Column(db.Integer, nullable=False, default=0)
    waste_percentage = db.Column(db.Numeric(5, 2), default=0)
    dynamic_discount_pct = db.Column(db.Numeric(5, 2), default=0)
    status           = db.Column(db.String(30), default='Produced')
    notes            = db.Column(db.Text)

    product = db.relationship('Product', backref='production_batches')
    branch  = db.relationship('Branch', backref='production_batches')

    @property
    def age_days(self):
        return (utcnow().date() - self.produced_at.date()).days
