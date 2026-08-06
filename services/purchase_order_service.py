from datetime import date
from decimal import Decimal

from clock import utcnow
from exceptions import ValidationError
from models import (
    FinancialTransaction,
    MaterialBatch,
    PurchaseOrder,
    PurchaseOrderItem,
    VendorProduct,
    db,
)


def _money(value):
    return Decimal(str(value or 0)).quantize(Decimal("0.01"))


def _batch_date(value):
    if isinstance(value, date):
        return value
    raw = (value or "").strip()
    if not raw:
        return None
    try:
        return date.fromisoformat(raw[:10])
    except ValueError:
        return None


class PurchaseOrderService:
    def __init__(
        self, inventory_service=None, finance_service=None, audit_service=None
    ):
        self.inventory_service = inventory_service
        self.finance_service = finance_service
        self.audit_service = audit_service

    def receive_purchase_order(
        self,
        purchase_order,
        actor_id=None,
        payment_method="",
        payment_amount=None,
        batch_details=None,
    ):
        if purchase_order is None:
            raise ValidationError("Purchase order not found.")
        status = (purchase_order.status or "draft").strip().lower()
        if status == "received":
            return {
                "movements": [],
                "transaction": self._existing_transaction(purchase_order),
            }
        if status == "cancelled":
            raise ValidationError("Cancelled purchase orders cannot be received.")

        items = purchase_order.items.all()
        if not items:
            raise ValidationError("Purchase order has no items to receive.")

        inventory = self._inventory_service()
        finance = self._finance_service()
        subtotal = Decimal("0")
        movements = []
        batch_details = batch_details or {}

        for index, item in enumerate(items):
            material = item.raw_material
            if material is None:
                raise ValidationError("Purchase order item is missing a raw material.")
            quantity = Decimal(str(item.quantity or 0))
            unit_cost = Decimal(str(item.unit_cost or 0))
            if quantity <= 0:
                raise ValidationError(
                    f"{material.name} quantity must be greater than zero."
                )
            if unit_cost < 0:
                raise ValidationError(f"{material.name} unit cost cannot be negative.")

            movement = inventory.increase_raw_material_stock(
                material,
                quantity,
                reason="purchase_order_received",
                created_by=actor_id,
            )
            if movement:
                movements.append(movement)
            subtotal += quantity * unit_cost
            self._upsert_vendor_product(
                purchase_order.vendor_id, material.id, unit_cost
            )

            row = (batch_details or {}).get(item.id) or {}
            batch_number = (row.get("batch_number") or "").strip()
            if not batch_number:
                batch_number = f"PO{purchase_order.id}-{material.id}"
            batch = MaterialBatch(
                raw_material_id=material.id,
                batch_number=batch_number,
                supplier_id=purchase_order.vendor_id,
                purchase_order_id=purchase_order.id,
                received_quantity=quantity,
                remaining_quantity=quantity,
                unit_cost=unit_cost,
                manufacturing_date=_batch_date(row.get("manufacturing_date")),
                expiry_date=_batch_date(row.get("expiry_date")),
                storage_location=(row.get("storage_location") or "").strip() or None,
                status="available",
                created_by=actor_id,
            )
            db.session.add(batch)

            material.last_purchased_at = utcnow()
            material.last_purchase_quantity = quantity
            material.last_purchase_unit_price = unit_cost

        finance.ensure_default_categories()
        category = finance.get_category("raw_material_purchase")
        if category is None:
            raise ValidationError(
                "Raw material purchase finance category is not configured."
            )

        received_at = utcnow()
        tax_amount = self._input_tax_credit_amount(purchase_order, subtotal)
        tds = finance.purchase_order_tds_preview(
            purchase_order,
            subtotal=subtotal,
            as_of=received_at,
        )
        booked_amount = _money(subtotal)
        if payment_amount is not None:
            requested = _money(payment_amount)
            if requested < 0:
                raise ValidationError("Payment amount cannot be negative.")
            booked_amount = min(requested, booked_amount)
        txn = finance.create_manual_transaction(
            transaction_type="expense",
            category_id=category.id,
            amount=booked_amount,
            tax_amount=tax_amount,
            tds_withheld=tds["tds_amount"],
            description=f"Purchase order #{purchase_order.id} received",
            counterparty=purchase_order.vendor.name if purchase_order.vendor else "",
            branch_id=None,
            payment_method=payment_method,
            created_by=actor_id,
            vendor_id=purchase_order.vendor_id,
            reference_purchase_order_id=purchase_order.id,
        )
        txn.is_auto_generated = True
        purchase_order.status = "received"
        purchase_order.received_at = received_at
        purchase_order.tds_applicable = bool(tds["applicable"])
        purchase_order.tds_section = tds["section"] or None
        purchase_order.tds_rate_percent = tds["rate_percent"]
        purchase_order.tds_base_amount = tds["base_amount"]
        purchase_order.tds_amount = tds["tds_amount"]
        purchase_order.tds_reason = tds["reason"][:255] if tds["reason"] else None
        purchase_order.tds_deducted_at = received_at if tds["applicable"] else None
        purchase_order.tds_deposit_due_date = tds["deposit_due_date"]

        self._audit_received(purchase_order, subtotal, tax_amount, tds, actor_id)
        return {"movements": movements, "transaction": txn}

    def payments(self, purchase_order):
        return (
            FinancialTransaction.query.filter_by(
                reference_purchase_order_id=purchase_order.id
            )
            .order_by(FinancialTransaction.created_at.asc(), FinancialTransaction.id.asc())
            .all()
        )

    def paid_amount(self, purchase_order):
        total = Decimal("0")
        for txn in self.payments(purchase_order):
            total += _money(txn.amount)
        return total.quantize(Decimal("0.01"))

    def remaining_amount(self, purchase_order):
        remaining = Decimal(str(purchase_order.subtotal or 0)) - self.paid_amount(
            purchase_order
        )
        return max(Decimal("0.00"), remaining).quantize(Decimal("0.01"))

    def record_purchase_payment(
        self,
        purchase_order,
        amount,
        payment_method="",
        references="",
        notes="",
        actor_id=None,
    ):
        if purchase_order is None:
            raise ValidationError("Purchase order not found.")
        if (purchase_order.status or "").strip().lower() == "cancelled":
            raise ValidationError("Cancelled purchase orders cannot receive payments.")
        amount = _money(amount)
        if amount <= 0:
            raise ValidationError("Payment amount must be greater than zero.")
        remaining = self.remaining_amount(purchase_order)
        if amount > remaining:
            raise ValidationError(
                f"Payment of ₹{amount} exceeds the remaining amount of ₹{remaining}."
            )
        finance = self._finance_service()
        finance.ensure_default_categories()
        category = finance.get_category("raw_material_purchase")
        if category is None:
            raise ValidationError(
                "Raw material purchase finance category is not configured."
            )
        description = f"Purchase order #{purchase_order.id} payment"
        if references:
            description += f" — {references[:200]}"
        if notes:
            description += f" ({notes[:120]})"
        txn = finance.create_manual_transaction(
            transaction_type="expense",
            category_id=category.id,
            amount=amount,
            description=description,
            counterparty=purchase_order.vendor.name if purchase_order.vendor else "",
            branch_id=None,
            payment_method=payment_method,
            created_by=actor_id,
            vendor_id=purchase_order.vendor_id,
            reference_purchase_order_id=purchase_order.id,
        )
        txn.is_auto_generated = True
        try:
            from bootstrap import get_container

            get_container().audit_service.log(
                actor_id,
                "payment_recorded",
                "PurchaseOrder",
                purchase_order.id,
                after={
                    "amount": float(amount),
                    "payment_method": payment_method,
                    "references": references,
                    "remaining": float(self.remaining_amount(purchase_order)),
                },
                change_summary=(
                    f"Payment of ₹{amount} recorded for purchase order "
                    f"#{purchase_order.id}."
                ),
            )
        except Exception:
            pass
        return txn

    def last_purchase_summary(self, material):
        row = (
            PurchaseOrderItem.query.join(PurchaseOrder)
            .filter(PurchaseOrderItem.raw_material_id == material.id)
            .order_by(PurchaseOrder.order_date.desc(), PurchaseOrder.id.desc())
            .first()
        )
        if row is None:
            return None
        return {
            "purchase_order": row.purchase_order,
            "quantity": row.quantity,
            "unit_cost": row.unit_cost,
            "vendor": row.purchase_order.vendor,
        }

    def _input_tax_credit_amount(self, purchase_order, subtotal):
        if not (purchase_order.vendor and purchase_order.vendor.gstin):
            return Decimal("0.00")
        rate = Decimal(str(purchase_order.gst_rate_percent or 0))
        if rate <= 0:
            return Decimal("0.00")
        return (Decimal(str(subtotal or 0)) * rate / Decimal("100")).quantize(
            Decimal("0.01")
        )

    def _upsert_vendor_product(self, vendor_id, raw_material_id, unit_cost):
        row = VendorProduct.query.filter_by(
            vendor_id=vendor_id,
            raw_material_id=raw_material_id,
        ).first()
        if row is None:
            row = VendorProduct(
                vendor_id=vendor_id,
                raw_material_id=raw_material_id,
                typical_unit_cost=unit_cost,
            )
            db.session.add(row)
        row.last_unit_cost = unit_cost
        row.updated_at = utcnow()
        return row

    def _existing_transaction(self, purchase_order):
        return FinancialTransaction.query.filter_by(
            reference_purchase_order_id=purchase_order.id
        ).first()

    def _inventory_service(self):
        if self.inventory_service is not None:
            return self.inventory_service
        from bootstrap import get_container

        return get_container().inventory_service

    def _finance_service(self):
        if self.finance_service is not None:
            return self.finance_service
        from bootstrap import get_container

        return get_container().finance_service

    def _audit_received(self, purchase_order, subtotal, tax_amount, tds, actor_id):
        audit = self.audit_service
        if audit is None:
            try:
                from bootstrap import get_container

                audit = get_container().audit_service
            except Exception:
                audit = None
        if audit is None:
            return
        try:
            audit.log(
                actor_id,
                "purchase_order_received",
                "PurchaseOrder",
                purchase_order.id,
                after={
                    "vendor_id": purchase_order.vendor_id,
                    "subtotal": float(subtotal or 0),
                    "tax_amount": float(tax_amount or 0),
                    "input_tax_credit_eligible": purchase_order.input_tax_credit_eligible,
                    "tds_amount": float(tds["tds_amount"] or 0),
                    "tds_section": tds["section"],
                    "tds_reason": tds["reason"],
                },
                change_summary=f"Purchase order #{purchase_order.id} received.",
            )
        except Exception:
            pass
