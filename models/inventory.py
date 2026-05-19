from datetime import datetime
import uuid
from .base import db

class RawMaterial(db.Model):
    __tablename__ = 'raw_materials'
    id            = db.Column(db.Integer, primary_key=True)
    name          = db.Column(db.String(120), nullable=False, unique=True)
    branch_id     = db.Column(db.Integer, db.ForeignKey('branches.id'))
    unit          = db.Column(db.String(30), nullable=False, default='kg')
    stock         = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    reorder_level = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    cost_per_unit = db.Column(db.Numeric(10, 2), default=0)
    supplier      = db.Column(db.String(120))
    notes         = db.Column(db.Text)
    is_active     = db.Column(db.Boolean, default=True)
    version       = db.Column(db.Integer, default=1, nullable=False)
    created_at    = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at    = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    recipe_items  = db.relationship('ProductMaterial', backref='raw_material', lazy='dynamic')

    branch = db.relationship('Branch', backref='raw_materials')

    @property
    def stock_status(self):
        stock = float(self.stock or 0)
        reorder = float(self.reorder_level or 0)
        if stock <= 0:
            return 'out_of_stock'
        if reorder > 0 and stock <= reorder:
            return 'low_stock'
        return 'in_stock'


class ProductMaterial(db.Model):
    __tablename__ = 'product_materials'
    id                = db.Column(db.Integer, primary_key=True)
    product_id        = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    raw_material_id   = db.Column(db.Integer, db.ForeignKey('raw_materials.id'), nullable=False)
    quantity_required = db.Column(db.Numeric(10, 2), nullable=False, default=0)

    __table_args__ = (
        db.UniqueConstraint('product_id', 'raw_material_id', name='uq_product_material'),
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
    created_at    = db.Column(db.DateTime, default=datetime.utcnow)

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
    created_at   = db.Column(db.DateTime, default=datetime.utcnow)

    @property
    def status(self):
        return 'Open' if self.is_active else 'Closed'


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
    created_at     = db.Column(db.DateTime, default=datetime.utcnow)

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
    produced_at      = db.Column(db.DateTime, default=datetime.utcnow)
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
        return (datetime.utcnow().date() - self.produced_at.date()).days
