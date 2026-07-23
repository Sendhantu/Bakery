from decimal import Decimal, InvalidOperation

from exceptions import ValidationError
from flask import current_app, url_for
from sqlalchemy import func

from models import (
    Notification,
    Product,
    ProductMaterial,
    ProductVariant,
    RawMaterial,
    StockMovement,
    User,
    db,
)
from utils.notifications import check_and_send_inventory_alerts
from utils.permissions import ADMIN_PORTAL_ROLES


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

    def low_stock_raw_materials(self, limit=None):
        query = RawMaterial.query.filter(
            RawMaterial.is_active == True,
            RawMaterial.stock <= RawMaterial.reorder_level,
        ).order_by(RawMaterial.stock.asc(), RawMaterial.name.asc())
        if limit:
            query = query.limit(limit)
        return query.all()

    def low_stock_product_variants(self, threshold=5, limit=None):
        query = (
            ProductVariant.query.join(Product)
            .filter(
                Product.is_active == True,
                ProductVariant.stock <= threshold,
            )
            .order_by(ProductVariant.stock.asc(), Product.name.asc())
        )
        if limit:
            query = query.limit(limit)
        return query.all()

    def product_stock_risk(self, limit=10):
        rows = (
            db.session.query(Product, RawMaterial, ProductMaterial.quantity_required)
            .join(ProductMaterial, ProductMaterial.product_id == Product.id)
            .join(RawMaterial, RawMaterial.id == ProductMaterial.raw_material_id)
            .filter(
                Product.is_active == True,
                RawMaterial.is_active == True,
                ProductMaterial.quantity_required > 0,
            )
            .order_by(Product.name.asc(), RawMaterial.stock.asc())
            .all()
        )
        by_product = {}
        for product, material, quantity_required in rows:
            required = Decimal(quantity_required or 0)
            if required <= 0:
                continue
            available_units = int(Decimal(material.stock or 0) // required)
            current = by_product.get(product.id)
            if current is None or available_units < current["available_units"]:
                by_product[product.id] = {
                    "product_id": product.id,
                    "product_name": product.name,
                    "available_units": max(0, available_units),
                    "limiting_material": material.name,
                    "material_stock": float(material.stock or 0),
                    "material_unit": material.unit,
                    "quantity_required": float(required),
                    "is_low": material.stock_status in {"low_stock", "out_of_stock"},
                }
        risks = sorted(
            by_product.values(),
            key=lambda row: (not row["is_low"], row["available_units"], row["product_name"]),
        )
        return risks[:limit] if limit else risks

    def _notify_admin_low_stock_crossing(self, material, previous_stock, new_stock):
        reorder_level = Decimal(material.reorder_level or 0)
        if Decimal(previous_stock or 0) <= reorder_level or Decimal(new_stock or 0) > reorder_level:
            return

        try:
            link = url_for("admin.inventory")
        except RuntimeError:
            link = "/admin/inventory"

        admins = User.query.filter(
            User.is_active == True,
            User.role.in_(ADMIN_PORTAL_ROLES),
        ).all()
        for admin in admins:
            db.session.add(
                Notification(
                    user_id=admin.id,
                    title=f"Low stock: {material.name}",
                    message=(
                        f"{material.name} is down to {new_stock} {material.unit}; "
                        f"reorder level is {material.reorder_level} {material.unit}."
                    ),
                    type="inventory",
                    link=link,
                )
            )

    def _record_material_change(
        self,
        material,
        change_amount,
        reason,
        reference_order_id=None,
        created_by=None,
    ):
        change = Decimal(change_amount or 0)
        if change == 0:
            return None

        previous_stock = Decimal(material.stock or 0)
        new_stock = previous_stock + change
        if new_stock < 0:
            raise ValidationError(f"Insufficient stock: {material.name}")

        material.stock = new_stock
        material.version = int(material.version or 0) + 1
        movement = StockMovement(
            raw_material_id=material.id,
            change_amount=change,
            stock_after=new_stock,
            reason=reason,
            reference_order_id=reference_order_id,
            created_by=created_by,
        )
        db.session.add(movement)
        self._notify_admin_low_stock_crossing(material, previous_stock, new_stock)
        self._audit_stock_change(
            movement,
            material,
            previous_stock,
            new_stock,
            created_by,
        )
        return movement

    def _audit_stock_change(self, movement, material, previous_stock, new_stock, actor_id):
        try:
            from bootstrap import get_container

            get_container().audit_service.log(
                actor_id,
                "stock_adjusted",
                "StockMovement",
                movement.id,
                before={"raw_material_id": material.id, "stock": float(previous_stock)},
                after={
                    "raw_material_id": material.id,
                    "stock": float(new_stock),
                    "change_amount": float(movement.change_amount or 0),
                    "reason": movement.reason,
                },
                branch_id=material.branch_id,
                change_summary=f"Stock adjusted for {material.name} ({movement.reason})",
            )
        except Exception:
            pass

    def increase_raw_material_stock(self, material, quantity, reason="manual_restock", created_by=None):
        change = Decimal(quantity or 0)
        if change <= 0:
            raise ValidationError("Restock quantity must be greater than zero.")
        return self._record_material_change(
            material,
            change,
            reason,
            created_by=created_by,
        )

    def set_raw_material_stock(self, material, new_stock, reason="correction", created_by=None):
        target = Decimal(new_stock or 0)
        if target < 0:
            raise ValidationError("Raw material stock cannot be negative.")
        return self._record_material_change(
            material,
            target - Decimal(material.stock or 0),
            reason,
            created_by=created_by,
        )

    def deduct_order_raw_materials(self, cart_items, order, created_by=None):
        requirements = {}
        for item in cart_items:
            product = item.product
            if product is None:
                continue
            recipe_items = product.recipe_items.all()
            if not recipe_items:
                current_app.logger.warning(
                    "missing_recipe_for_order_item product_id=%s order_id=%s",
                    item.product_id,
                    order.id,
                )
                continue
            for recipe_item in recipe_items:
                required = Decimal(recipe_item.quantity_required or 0) * int(item.quantity or 0)
                if required <= 0:
                    continue
                bucket = requirements.setdefault(
                    recipe_item.raw_material_id,
                    {"quantity": Decimal("0"), "products": []},
                )
                bucket["quantity"] += required
                bucket["products"].append(product.name)

        changed_material_ids = []
        for material_id, requirement in requirements.items():
            material = db.session.get(RawMaterial, material_id, with_for_update=True)
            if material is None or not material.is_active:
                current_app.logger.warning(
                    "inactive_or_missing_recipe_material material_id=%s order_id=%s",
                    material_id,
                    order.id,
                )
                continue
            required = requirement["quantity"]
            if Decimal(material.stock or 0) < required:
                raise ValidationError(f"Insufficient stock: {material.name}")
            self._record_material_change(
                material,
                -required,
                "order_deduction",
                reference_order_id=order.id,
                created_by=created_by,
            )
            changed_material_ids.append(material.id)

        return changed_material_ids
