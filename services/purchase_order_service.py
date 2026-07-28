from decimal import Decimal

from clock import utcnow
from exceptions import ValidationError
from models import (
    FinancialTransaction,
    PurchaseOrder,
    VendorProduct,
    db,
)


class PurchaseOrderService:
    def __init__(
        self, inventory_service=None, finance_service=None, audit_service=None
    ):
        self.inventory_service = inventory_service
        self.finance_service = finance_service
        self.audit_service = audit_service

    def receive_purchase_order(self, purchase_order, actor_id=None):
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

        for item in items:
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

        finance.ensure_default_categories()
        category = finance.get_category("raw_material_purchase")
        if category is None:
            raise ValidationError(
                "Raw material purchase finance category is not configured."
            )

        tax_amount = self._input_tax_credit_amount(purchase_order, subtotal)
        txn = finance.create_manual_transaction(
            transaction_type="expense",
            category_id=category.id,
            amount=subtotal.quantize(Decimal("0.01")),
            tax_amount=tax_amount,
            description=f"Purchase order #{purchase_order.id} received",
            counterparty=purchase_order.vendor.name if purchase_order.vendor else "",
            branch_id=None,
            created_by=actor_id,
            vendor_id=purchase_order.vendor_id,
            reference_purchase_order_id=purchase_order.id,
        )
        txn.is_auto_generated = True
        purchase_order.status = "received"
        purchase_order.received_at = utcnow()

        self._audit_received(purchase_order, subtotal, tax_amount, actor_id)
        return {"movements": movements, "transaction": txn}

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

    def _audit_received(self, purchase_order, subtotal, tax_amount, actor_id):
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
                },
                change_summary=f"Purchase order #{purchase_order.id} received.",
            )
        except Exception:
            pass
