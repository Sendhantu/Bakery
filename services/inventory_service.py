from contextlib import nullcontext
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from clock import utcnow
from exceptions import ValidationError
from flask import current_app, url_for
from sqlalchemy import func

from models import (
    BATCH_CONSUMABLE_STATUSES,
    BATCH_STATUS_LABELS,
    BATCH_UNUSABLE_STATUSES,
    STOCK_MOVEMENT_REASON_LABELS,
    MaterialBatch,
    MaterialDocument,
    Notification,
    Product,
    ProductMaterial,
    ProductVariant,
    PurchaseOrder,
    PurchaseOrderItem,
    RawMaterial,
    StockMovement,
    User,
    db,
)
from utils.notifications import check_and_send_inventory_alerts
from utils.permissions import ADMIN_PORTAL_ROLES


STOCK_DECREASE_REASONS = {"usage", "wastage", "damage", "expired", "return_to_supplier"}


def _to_decimal(value, label):
    try:
        return Decimal(str(value or 0))
    except (InvalidOperation, TypeError, ValueError):
        raise ValidationError(f"Please enter a valid {label}.")


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
        session = db.session()
        transaction = nullcontext() if session.in_transaction() else db.session.begin()
        with transaction:
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
        notes=None,
        reference_purchase_order_id=None,
        reference_batch_id=None,
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
            notes=(notes or "").strip() or None,
            reference_order_id=reference_order_id,
            reference_purchase_order_id=reference_purchase_order_id,
            reference_batch_id=reference_batch_id,
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

    def _consume_batches(
        self,
        material,
        quantity,
        reason,
        created_by=None,
        notes=None,
        reference_order_id=None,
        reference_purchase_order_id=None,
    ):
        """Consume `quantity` from the material's batches using FEFO (then FIFO).

        Only batches that are usable (available / partially used) are consumed.
        Returns the list of batch objects touched.
        """
        batches = list(
            material.batches.filter(MaterialBatch.status.in_(BATCH_CONSUMABLE_STATUSES))
        )
        if not batches:
            return []

        def sort_key(batch):
            return (
                batch.expiry_date is None,
                batch.expiry_date or date.max,
                batch.received_at or batch.created_at or date(2000, 1, 1),
                batch.id,
            )

        remaining = Decimal(str(quantity or 0))
        consumed = []
        for batch in sorted(batches, key=sort_key):
            if remaining <= 0:
                break
            available = Decimal(str(batch.remaining_quantity or 0))
            if available <= 0:
                continue
            take = min(remaining, available)
            batch.remaining_quantity = available - take
            batch.status = (
                "fully_used"
                if Decimal(str(batch.remaining_quantity)) <= 0
                else "partially_used"
            )
            remaining -= take
            consumed.append(batch)
        if consumed:
            db.session.add_all(consumed)
        return consumed

    def _record_stock_action(
        self,
        material,
        quantity,
        reason,
        actor_id=None,
        notes=None,
        reference_order_id=None,
        reference_purchase_order_id=None,
        reference_batch_id=None,
    ):
        qty = _to_decimal(quantity, "quantity")
        if qty <= 0:
            raise ValidationError("Quantity must be greater than zero.")
        if reason in STOCK_DECREASE_REASONS and Decimal(str(material.stock or 0)) < qty:
            raise ValidationError(f"Insufficient stock: {material.name}")

        change_amount = -qty if reason in STOCK_DECREASE_REASONS else qty
        if reason in STOCK_DECREASE_REASONS and reason != "return_to_supplier":
            self._consume_batches(
                material,
                qty,
                reason,
                created_by=actor_id,
                notes=notes,
                reference_order_id=reference_order_id,
                reference_purchase_order_id=reference_purchase_order_id,
            )
        movement = self._record_material_change(
            material,
            change_amount,
            reason,
            created_by=actor_id,
            notes=notes,
            reference_order_id=reference_order_id,
            reference_purchase_order_id=reference_purchase_order_id,
            reference_batch_id=reference_batch_id,
        )
        return {"movement": movement, "batch_touched": bool(reference_batch_id)}

    def record_usage(
        self,
        material,
        quantity,
        actor_id=None,
        notes=None,
        reference_order_id=None,
        reference_batch_id=None,
    ):
        return self._record_stock_action(
            material,
            quantity,
            "usage",
            actor_id=actor_id,
            notes=notes,
            reference_order_id=reference_order_id,
            reference_batch_id=reference_batch_id,
        )

    def record_wastage(
        self,
        material,
        quantity,
        actor_id=None,
        notes=None,
        reference_order_id=None,
    ):
        return self._record_stock_action(
            material,
            quantity,
            "wastage",
            actor_id=actor_id,
            notes=notes,
            reference_order_id=reference_order_id,
        )

    def record_damage(
        self,
        material,
        quantity,
        actor_id=None,
        notes=None,
        reference_order_id=None,
    ):
        return self._record_stock_action(
            material,
            quantity,
            "damage",
            actor_id=actor_id,
            notes=notes,
            reference_order_id=reference_order_id,
        )

    def record_expired(
        self,
        material,
        quantity,
        actor_id=None,
        notes=None,
        reference_order_id=None,
    ):
        return self._record_stock_action(
            material,
            quantity,
            "expired",
            actor_id=actor_id,
            notes=notes,
            reference_order_id=reference_order_id,
        )

    def return_to_supplier(
        self,
        material,
        quantity,
        actor_id=None,
        notes=None,
        reference_batch_id=None,
    ):
        return self._record_stock_action(
            material,
            quantity,
            "return_to_supplier",
            actor_id=actor_id,
            notes=notes,
            reference_batch_id=reference_batch_id,
        )

    def manual_adjust(
        self,
        material,
        quantity,
        actor_id=None,
        notes=None,
        reference_purchase_order_id=None,
    ):
        """Apply a signed correction. Positive adds stock, negative removes it."""
        qty = _to_decimal(quantity, "quantity")
        if qty == 0:
            raise ValidationError("Adjustment quantity cannot be zero.")
        if qty < 0 and Decimal(str(material.stock or 0)) < -qty:
            raise ValidationError(f"Insufficient stock: {material.name}")
        if qty < 0:
            self._consume_batches(
                material,
                -qty,
                "correction",
                created_by=actor_id,
                notes=notes,
                reference_purchase_order_id=reference_purchase_order_id,
            )
        movement = self._record_material_change(
            material,
            qty,
            "correction",
            created_by=actor_id,
            notes=notes,
            reference_purchase_order_id=reference_purchase_order_id,
        )
        return {"movement": movement}

    def set_batch_status(
        self, batch, status, actor_id=None, notes=None
    ):
        if batch is None:
            raise ValidationError("Batch not found.")
        if status not in BATCH_STATUS_LABELS:
            raise ValidationError("Choose a valid batch status.")
        allowed_transitions = {
            "available",
            "partially_used",
            "fully_used",
            "expired",
            "damaged",
            "returned",
            "blocked",
        }
        if status not in allowed_transitions:
            raise ValidationError("Choose a valid batch status.")
        previous = batch.status
        batch.status = status
        batch.notes = (notes or "").strip() or batch.notes
        try:
            from bootstrap import get_container

            get_container().audit_service.log(
                actor_id,
                "material_batch_status_changed",
                "MaterialBatch",
                batch.id,
                before={"status": previous},
                after={"status": status, "notes": batch.notes},
                change_summary=(
                    f"Batch {batch.batch_number} for {batch.raw_material.name} "
                    f"marked {BATCH_STATUS_LABELS.get(status, status)}."
                ),
            )
        except Exception:
            pass
        return batch

    def refresh_batch_statuses(self, material):
        """Mark batches expired when their expiry date has passed."""
        changed = []
        for batch in list(material.batches):
            if (
                batch.expiry_date
                and batch.expiry_date < utcnow().date()
                and batch.status not in BATCH_UNUSABLE_STATUSES
                and Decimal(str(batch.remaining_quantity or 0)) > 0
            ):
                batch.status = "expired"
                changed.append(batch)
        return changed

    def update_material_details(self, material, form, actor_id=None):
        """Update only editable detail fields. Stock and cost are managed by ledger actions."""
        before = {
            "name": material.name,
            "sku": material.sku,
            "category": material.category,
            "unit": material.unit,
            "reorder_level": str(material.reorder_level),
            "min_stock": str(material.min_stock or ""),
            "max_stock": str(material.max_stock or ""),
            "preferred_supplier_id": material.preferred_supplier_id,
            "storage_location": material.storage_location,
            "shelf_life_days": material.shelf_life_days,
            "tax_rate_percent": str(material.tax_rate_percent or ""),
            "expiring_soon_days": material.expiring_soon_days,
            "notes": material.notes,
        }
        name = (form.get("name") or "").strip()
        if not name:
            raise ValidationError("Material name is required.")
        if RawMaterial.query.filter(
            func.lower(RawMaterial.name) == name.lower(),
            RawMaterial.id != material.id,
        ).first():
            raise ValidationError("Another material already uses that name.")

        material.name = name
        material.sku = (form.get("sku") or "").strip() or None
        material.category = (form.get("category") or "").strip() or None
        material.unit = (form.get("unit") or "").strip() or "kg"

        def _numeric(field, label, required=False):
            raw = (form.get(field) or "").strip()
            if not raw:
                if required:
                    raise ValidationError(f"{label} is required.")
                return None
            value = _to_decimal(raw, label)
            if value < 0:
                raise ValidationError(f"{label} cannot be negative.")
            return value

        material.reorder_level = _numeric("reorder_level", "reorder level", required=True) or Decimal("0")
        material.min_stock = _numeric("min_stock", "minimum stock")
        material.max_stock = _numeric("max_stock", "maximum stock")
        material.tax_rate_percent = _numeric("tax_rate_percent", "tax rate")

        if (
            material.min_stock is not None
            and material.max_stock is not None
            and material.max_stock < material.min_stock
        ):
            raise ValidationError("Maximum stock cannot be below minimum stock.")

        shelf_life_raw = (form.get("shelf_life_days") or "").strip()
        material.shelf_life_days = (
            max(0, int(shelf_life_raw)) if shelf_life_raw else None
        )
        expiring_raw = (form.get("expiring_soon_days") or "").strip()
        material.expiring_soon_days = max(1, int(expiring_raw or 14))

        preferred_supplier_raw = (form.get("preferred_supplier_id") or "").strip()
        material.preferred_supplier_id = (
            int(preferred_supplier_raw) if preferred_supplier_raw else None
        )
        material.storage_location = (form.get("storage_location") or "").strip() or None
        material.notes = (form.get("notes") or "").strip() or None
        material.updated_by = actor_id

        try:
            from bootstrap import get_container

            get_container().audit_service.log(
                actor_id,
                "raw_material_details_updated",
                "RawMaterial",
                material.id,
                before=before,
                after={
                    "name": material.name,
                    "sku": material.sku,
                    "category": material.category,
                    "unit": material.unit,
                    "reorder_level": str(material.reorder_level),
                    "min_stock": str(material.min_stock or ""),
                    "max_stock": str(material.max_stock or ""),
                    "preferred_supplier_id": material.preferred_supplier_id,
                    "storage_location": material.storage_location,
                    "shelf_life_days": material.shelf_life_days,
                    "tax_rate_percent": str(material.tax_rate_percent or ""),
                    "expiring_soon_days": material.expiring_soon_days,
                    "notes": material.notes,
                },
                change_summary=f"Raw material details updated: {material.name}.",
            )
        except Exception:
            pass
        return material

    def stock_summary(self, materials):
        total = len(materials)
        low = 0
        out = 0
        expiring = 0
        expired = 0
        value = Decimal("0")
        for material in materials:
            if not material.is_active:
                continue
            if material.stock_status == "out_of_stock":
                out += 1
            elif material.stock_status == "low_stock":
                low += 1
            expiry = material.expiry_summary
            if expiry["status"] == "expiring_soon":
                expiring += 1
            elif expiry["status"] == "expired":
                expired += 1
            value += material.inventory_value
        return {
            "total": total,
            "low": low,
            "out": out,
            "expiring": expiring,
            "expired": expired,
            "value": value.quantize(Decimal("0.01")),
        }

    def material_detail_context(self, material, movements_limit=25):
        self.refresh_batch_statuses(material)
        movements = (
            material.stock_movements.order_by(
                StockMovement.created_at.desc(), StockMovement.id.desc()
            )
            .limit(movements_limit)
            .all()
        )
        batches = list(
            material.batches.order_by(
                MaterialBatch.expiry_date.asc(),
                MaterialBatch.received_at.desc(),
            )
        )
        documents = list(
            material.documents.order_by(MaterialDocument.created_at.desc()).all()
        )
        purchases = (
            db.session.query(PurchaseOrderItem, PurchaseOrder)
            .join(PurchaseOrder, PurchaseOrder.id == PurchaseOrderItem.purchase_order_id)
            .filter(PurchaseOrderItem.raw_material_id == material.id)
            .order_by(PurchaseOrder.order_date.desc(), PurchaseOrder.id.desc())
            .all()
        )
        supplier_name = None
        if material.preferred_supplier:
            supplier_name = material.preferred_supplier.name
        return {
            "material": material,
            "batches": batches,
            "movements": movements,
            "documents": documents,
            "purchases": purchases,
            "supplier_name": supplier_name or material.supplier,
            "stock_status": material.stock_status,
            "expiry_summary": material.expiry_summary,
            "usable_quantity": material.usable_quantity,
            "inventory_value": material.inventory_value,
            "movement_reason_labels": STOCK_MOVEMENT_REASON_LABELS,
            "batch_status_labels": BATCH_STATUS_LABELS,
        }

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
            self._consume_batches(
                material,
                required,
                "order_deduction",
                created_by=created_by,
                reference_order_id=order.id,
            )
            self._record_material_change(
                material,
                -required,
                "order_deduction",
                reference_order_id=order.id,
                created_by=created_by,
            )
            changed_material_ids.append(material.id)

        return changed_material_ids
