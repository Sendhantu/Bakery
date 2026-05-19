from datetime import datetime
from .base import db

PRODUCT_FALLBACK_IMAGES = {
    'cakes':    'https://images.unsplash.com/photo-1548865164-1f50430ddd6f?auto=format&fit=crop&w=1200&q=80',
    'pastries': 'https://images.unsplash.com/photo-1758797957671-20943209f1f5?auto=format&fit=crop&w=1200&q=80',
    'cookies':  'https://images.unsplash.com/photo-1639678114429-a915fdb55000?auto=format&fit=crop&w=1200&q=80',
    'breads':   'https://images.unsplash.com/photo-1562099870-a3c3f2f3b44d?auto=format&fit=crop&w=1200&q=80',
    'cupcakes': 'https://images.unsplash.com/photo-1486427944299-d1955d23e34d?auto=format&fit=crop&w=1200&q=80',
}

class Category(db.Model):
    __tablename__ = 'categories'
    id       = db.Column(db.Integer, primary_key=True)
    name     = db.Column(db.String(100), nullable=False, unique=True)
    icon     = db.Column(db.String(50), default='🎂')
    products = db.relationship('Product', backref='category', lazy='dynamic')


class Product(db.Model):
    __tablename__ = 'products'
    id            = db.Column(db.Integer, primary_key=True)
    name          = db.Column(db.String(200), nullable=False)
    description   = db.Column(db.Text)
    ingredients   = db.Column(db.Text)
    preparation   = db.Column(db.Text)
    base_price    = db.Column(db.Numeric(10, 2), nullable=False)
    image         = db.Column(db.String(255), default='default-product.jpg')
    image_url     = db.Column(db.String(512))
    category_id   = db.Column(db.Integer, db.ForeignKey('categories.id'))
    is_eggless    = db.Column(db.Boolean, default=False)
    is_active     = db.Column(db.Boolean, default=True)
    is_featured   = db.Column(db.Boolean, default=False)
    preorder_required = db.Column(db.Boolean, default=False)
    minimum_notice_hours = db.Column(db.Integer, default=24)
    occasion_tags = db.Column(db.String(300))
    shelf_life_hours = db.Column(db.Integer, default=24)
    version = db.Column(db.Integer, default=1, nullable=False)
    created_at    = db.Column(db.DateTime, default=datetime.utcnow)

    variants     = db.relationship('ProductVariant', backref='product', lazy='dynamic', cascade='all, delete-orphan')
    cart_items   = db.relationship('Cart', backref='product', lazy='dynamic')
    wish_items   = db.relationship('Wishlist', backref='product', lazy='dynamic')
    reviews      = db.relationship('Review', backref='product', lazy='dynamic')
    order_items  = db.relationship('OrderItem', backref='product', lazy='dynamic')
    recipe_items = db.relationship('ProductMaterial', backref='product', lazy='dynamic', cascade='all, delete-orphan')

    __table_args__ = (
        db.Index('idx_product_active_category', 'is_active', 'category_id'),
        db.Index('idx_product_is_featured', 'is_featured'),
    )

    @property
    def avg_rating(self):
        cached = getattr(self, '_avg_rating_cache', None)
        if cached is not None:
            return cached
        reviews = self.reviews.all()
        if not reviews:
            return 0
        return round(sum(r.rating for r in reviews) / len(reviews), 1)

    @property
    def review_count(self):
        cached = getattr(self, '_review_count_cache', None)
        if cached is not None:
            return cached
        return self.reviews.count()

    @property
    def total_stock(self):
        cached = getattr(self, '_total_stock_cache', None)
        if cached is not None:
            return cached
        return sum(v.stock for v in self.variants.all()) or 0

    @property
    def stock_status(self):
        total = self.total_stock
        if total == 0: return 'out_of_stock'
        if total <= 5: return 'few_left'
        return 'in_stock'

    @property
    def default_variant_id(self):
        cached = getattr(self, '_default_variant_id_cache', None)
        if cached is not None:
            return cached
        variant = self.variants.order_by(ProductVariant.id.asc()).first()
        return variant.id if variant else None

    @property
    def image_src(self):
        from flask import url_for
        if self.image_url:
            return self.image_url
        if not self.image or self.image == 'default-product.jpg':
            return self.fallback_image_src
        if self.image.startswith(('http://', 'https://')):
            return self.image
        return url_for('static', filename=f'images/products/{self.image}')

    @property
    def fallback_image_src(self):
        category_name = (self.category.name if self.category else '').lower()
        return PRODUCT_FALLBACK_IMAGES.get(category_name, PRODUCT_FALLBACK_IMAGES['cakes'])

    @property
    def current_price(self):
        try:
            from flask import current_app

            if current_app:
                from bootstrap import get_container

                return get_container().pricing_service.resolve_product_price(self)["price"]
        except Exception:
            return self.base_price
        return self.base_price


class ProductVariant(db.Model):
    __tablename__ = 'product_variants'
    id         = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    branch_id  = db.Column(db.Integer, db.ForeignKey('branches.id'))
    name       = db.Column(db.String(100), nullable=False)
    price      = db.Column(db.Numeric(10, 2), nullable=False)
    stock      = db.Column(db.Integer, default=0)
    sku        = db.Column(db.String(100))
    barcode    = db.Column(db.String(100), unique=True)
    version    = db.Column(db.Integer, default=1, nullable=False)

    branch = db.relationship('Branch', backref='product_variants')

    @property
    def current_price(self):
        try:
            from flask import current_app

            if current_app:
                from bootstrap import get_container

                return get_container().pricing_service.resolve_product_price(
                    self.product,
                    self,
                )["price"]
        except Exception:
            return self.price
        return self.price


class Review(db.Model):
    __tablename__ = 'reviews'
    id         = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)
    user_id    = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    rating     = db.Column(db.Integer, nullable=False)
    comment    = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
