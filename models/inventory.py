from datetime import datetime
from .base import db

class RawMaterial(db.Model):
    __tablename__ = 'raw_materials'
    id            = db.Column(db.Integer, primary_key=True)
    name          = db.Column(db.String(120), nullable=False, unique=True)
    unit          = db.Column(db.String(30), nullable=False, default='kg')
    stock         = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    reorder_level = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    cost_per_unit = db.Column(db.Numeric(10, 2), default=0)
    supplier      = db.Column(db.String(120))
    notes         = db.Column(db.Text)
    is_active     = db.Column(db.Boolean, default=True)
    created_at    = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at    = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    recipe_items  = db.relationship('ProductMaterial', backref='raw_material', lazy='dynamic')

    @property
    def stock_status(self):
        stock = float(self.stock or 0)
        reorder = float(self.reorder_level or 0)
        if stock <= 0:         return 'out_of_stock'
        if reorder > 0 and stock <= reorder: return 'low_stock'
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
