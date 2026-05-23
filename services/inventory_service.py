from decimal import Decimal, InvalidOperation

from exceptions import ValidationError
from models import Product, ProductVariant, db
from utils.notifications import check_and_send_inventory_alerts


class InventoryService:
    def dispatch_low_stock_alerts(self):
        return check_and_send_inventory_alerts()

    def ensure_product_inventory(self, product, default_stock=0, default_name="Standard"):
        if product is None:
            return None

        variant = product.variants.order_by(ProductVariant.id.asc()).first()
        if variant is not None:
            return variant

        variant = ProductVariant(
            product_id=product.id,
            name=default_name,
            price=Decimal(str(product.base_price or 0)),
            stock=max(0, int(default_stock or 0)),
        )
        db.session.add(variant)
        return variant

    def backfill_missing_product_variants(self):
        created = 0
        products = Product.query.all()
        for product in products:
            if product.variants.count() > 0:
                continue
            self.ensure_product_inventory(product)
            created += 1

        if created:
            db.session.commit()
        return created

    def sync_product_variants(self, product, variant_rows):
        from models import ProductVariant
        # Run normalization and DB updates in a transaction to ensure atomic changes
        with db.session.begin():
            existing_by_id = {variant.id: variant for variant in product.variants.all()}
            normalized_rows = []

            for row in variant_rows:
                variant_id = row.get("id")
                name = (row.get("name") or "").strip()
                raw_price = str(row.get("price") or "").strip()
                raw_stock = str(row.get("stock") or "").strip()

                if not name and not raw_price and not raw_stock and not variant_id:
                    continue

                if not raw_price:
                    raise ValidationError("Every product variant needs a price.")

                try:
                    price = Decimal(raw_price)
                except (InvalidOperation, TypeError, ValueError):
                    raise ValidationError("Please enter a valid variant price.")

                try:
                    stock = int(raw_stock or 0)
                except (TypeError, ValueError):
                    raise ValidationError("Please enter a valid whole-number stock value.")

                if price < 0:
                    raise ValidationError("Variant price cannot be negative.")
                if stock < 0:
                    raise ValidationError("Variant stock cannot be negative.")

                normalized_rows.append(
                    {
                        "id": int(variant_id) if variant_id else None,
                        "name": name or "Standard",
                        "price": price,
                        "stock": stock,
                    }
                )

            if not normalized_rows:
                normalized_rows.append(
                    {
                        "id": None,
                        "name": "Standard",
                        "price": Decimal(str(product.base_price or 0)),
                        "stock": 0,
                    }
                )

            submitted_ids = set()
            for row in normalized_rows:
                variant = existing_by_id.get(row["id"]) if row["id"] else None
                if variant is None:
                    variant = ProductVariant(product_id=product.id)
                    db.session.add(variant)
                    db.session.flush()

                variant.name = row["name"]
                variant.price = row["price"]
                variant.stock = row["stock"]

                if variant.id is not None:
                    submitted_ids.add(variant.id)

            for existing_id, existing_variant in list(existing_by_id.items()):
                if existing_id not in submitted_ids:
                    db.session.delete(existing_variant)

            return normalized_rows
