import json
import os
from decimal import Decimal

from app import create_app
from models import db, Category, Product, ProductVariant

PRODUCTS_JSON = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "products.json")

CATEGORY_ICONS = {
    "Cakes": "🎂",
    "Pastries": "🥐",
    "Cookies": "🍪",
    "Breads": "🍞",
    "Cupcakes": "🧁",
    "Pies": "🥧",
}

PLACEHOLDER_IMAGES = {None, "", "default-product.jpg"}


def load_products():
    if not os.path.exists(PRODUCTS_JSON):
        raise FileNotFoundError(
            f"Product data file not found: {PRODUCTS_JSON}."
        )
    with open(PRODUCTS_JSON, "r", encoding="utf-8") as handle:
        return json.load(handle)


def seed_products(app):
    with app.app_context():
        products = load_products()

        categories = {cat.name: cat for cat in Category.query.all()}

        for name, icon in CATEGORY_ICONS.items():
            if name not in categories:
                category = Category(name=name, icon=icon)
                db.session.add(category)
                db.session.flush()
                categories[name] = category

        for pd in products:
            category = categories.get(pd["category"])
            if category is None:
                category = Category(name=pd["category"], icon=CATEGORY_ICONS.get(pd["category"], "🎂"))
                db.session.add(category)
                db.session.flush()
                categories[pd["category"]] = category

        db.session.commit()

        for pd in products:
            existing = Product.query.filter_by(name=pd["name"]).first()
            if existing:
                if existing.image in PLACEHOLDER_IMAGES and pd.get("image"):
                    existing.image = pd["image"]
                continue

            product = Product(
                name=pd["name"],
                description=pd.get("description"),
                ingredients=pd.get("ingredients"),
                preparation=pd.get("preparation"),
                base_price=Decimal(str(pd.get("base_price", 0))),
                image=pd.get("image"),
                category_id=categories[pd["category"]].id if pd.get("category") else None,
                is_eggless=pd.get("is_eggless", False),
                is_active=pd.get("is_active", True),
                is_featured=pd.get("is_featured", False),
                occasion_tags=pd.get("occasion_tags", ""),
            )
            db.session.add(product)
            db.session.flush()

            for variant in pd.get("variants", []):
                db.session.add(ProductVariant(
                    product_id=product.id,
                    name=variant.get("name", "Default"),
                    price=Decimal(str(variant.get("price", 0))),
                    stock=int(variant.get("stock", 0)),
                ))

        db.session.commit()
        print(f"Seeded {len(products)} products from {PRODUCTS_JSON}.")


if __name__ == "__main__":
    app = create_app(os.environ.get("FLASK_ENV", "development"))
    seed_products(app)
