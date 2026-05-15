from datetime import datetime
from .base import db

class Cart(db.Model):
    __tablename__ = 'cart'
    id         = db.Column(db.Integer, primary_key=True)
    user_id    = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    variant_id = db.Column(db.Integer, db.ForeignKey('product_variants.id'))
    quantity   = db.Column(db.Integer, default=1)
    added_at   = db.Column(db.DateTime, default=datetime.utcnow)
    variant    = db.relationship('ProductVariant')


class Wishlist(db.Model):
    __tablename__ = 'wishlist'
    id         = db.Column(db.Integer, primary_key=True)
    user_id    = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    added_at   = db.Column(db.DateTime, default=datetime.utcnow)


class SavedAddress(db.Model):
    __tablename__ = 'saved_addresses'
    id            = db.Column(db.Integer, primary_key=True)
    user_id       = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    label         = db.Column(db.String(60), nullable=False, default='Saved Address')
    address_line1 = db.Column(db.String(255), nullable=False)
    address_line2 = db.Column(db.String(255))
    city          = db.Column(db.String(100), nullable=False)
    pincode       = db.Column(db.String(10), nullable=False)
    phone         = db.Column(db.String(20), nullable=False)
    latitude      = db.Column(db.Float)
    longitude     = db.Column(db.Float)
    is_default    = db.Column(db.Boolean, default=False)
    created_at    = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at    = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    @property
    def full_address(self):
        parts = [self.address_line1]
        if self.address_line2:
            parts.append(self.address_line2)
        parts.append(f'{self.city} - {self.pincode}')
        return ', '.join(parts)
