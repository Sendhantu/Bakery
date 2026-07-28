from __future__ import annotations

from decimal import Decimal
from typing import Dict, List, Optional

from clock import utcnow
from exceptions import ValidationError
from models import (
    Delivery,
    Order,
    ProductVariant,
    Refund,
    StockMovement,
    db,
)


TERMINAL_REFUND_BLOCKED_STATUSES = {"DELIVERED"}
ALREADY_REVERSED_STATUSES = {"CANCELLED", "REFUNDED"}


def _decimal(value) -> Decimal:
    return Decimal(str(value or 0))


class OrderReversalService:
    """Append-only cancellation/refund workflow for stock, finance, realtime, and audit."""

    def __init__(
        self,
        *,
        inventory_service=None,
        finance_service=None,
        audit_service=None,
        push_service=None,
    ):
        self.inventory_service = inventory_service
        self.finance_service = finance_service
        self.audit_service = audit_service
        self.push_service = push_service

    def cancel_or_refund_order(
        self,
        order: Order,
        *,
        reason: str,
        actor_id: Optional[int] = None,
        reverse_stock: bool = False,
        allow_paid_refund: bool = False,
        initiated_by: str = "admin",
    ) -> Dict:
        reason = (reason or "").strip()
        if not reason:
            raise ValidationError("A cancellation/refund reason is required.")
        if order.status in ALREADY_REVERSED_STATUSES:
            raise ValidationError("This order is already cancelled or refunded.")
        if order.status in TERMINAL_REFUND_BLOCKED_STATUSES:
            raise ValidationError(
                "Delivered orders require a separate post-delivery refund workflow."
            )

        before = {
            "status": order.status,
            "payment_status": order.payment_status,
        }
        is_paid = (order.payment_status or "").upper() == "PAID" or (
            order.payment and (order.payment.status or "").upper() == "PAID"
        )
        if is_paid and not allow_paid_refund:
            raise ValidationError("Paid orders must use the refund action.")

        stock_movements: List[StockMovement] = []
        restored_variant_ids: List[int] = []
        if reverse_stock:
            stock_movements = self._reverse_raw_material_movements(order, actor_id=actor_id)
            restored_variant_ids = self._reverse_variant_stock(order)

        refund = None
        finance_txn = None
        action = "order_cancelled"
        new_status = "CANCELLED"

        if is_paid:
            action = "order_refunded"
            new_status = "REFUNDED"
            refund = self._create_refund_record(order, reason)
            self._transition_payment_to_refunded(order, actor_id=actor_id, reason=reason)
            if self.finance_service is not None:
                finance_txn = self.finance_service.record_refund_from_order(
                    order,
                    amount=_decimal(order.total),
                    reason=reason,
                    actor_id=actor_id,
                )
            order.payment_status = "REFUNDED"
        else:
            self._cancel_pending_payment(order, actor_id=actor_id, reason=reason)

        order.status = new_status
        order.mark_status_change()
        self._free_delivery_assignment(order)
        self._audit(order, action, before, reason, reverse_stock, actor_id, initiated_by)

        return {
            "action": action,
            "order": order,
            "refund": refund,
            "finance_transaction": finance_txn,
            "stock_movements": stock_movements,
            "restored_variant_ids": restored_variant_ids,
            "reverse_stock": reverse_stock,
            "reason": reason,
        }

    def _reverse_raw_material_movements(self, order: Order, actor_id=None):
        if self.inventory_service is None:
            return []

        deduction_rows = StockMovement.query.filter_by(
            reference_order_id=order.id,
            reason="order_deduction",
        ).all()
        if not deduction_rows:
            return []

        existing_reversal_count = StockMovement.query.filter_by(
            reference_order_id=order.id,
            reason="order_cancellation_reversal",
        ).count()
        if existing_reversal_count:
            return []

        created = []
        for movement in deduction_rows:
            material = movement.raw_material
            if material is None:
                continue
            reversal_qty = -_decimal(movement.change_amount)
            if reversal_qty <= 0:
                continue
            created.append(
                self.inventory_service._record_material_change(
                    material,
                    reversal_qty,
                    "order_cancellation_reversal",
                    reference_order_id=order.id,
                    created_by=actor_id,
                )
            )
        return [movement for movement in created if movement is not None]

    def _reverse_variant_stock(self, order: Order):
        restored = []
        for item in order.items.all():
            if not item.variant_id:
                continue
            variant = db.session.get(ProductVariant, item.variant_id, with_for_update=True)
            if variant is None:
                continue
            variant.stock = int(variant.stock or 0) + int(item.quantity or 0)
            variant.version = int(variant.version or 0) + 1
            restored.append(variant.id)
        return restored

    def _create_refund_record(self, order: Order, reason: str):
        existing = Refund.query.filter_by(order_id=order.id, status="PROCESSING").first()
        if existing:
            return existing
        existing = Refund.query.filter_by(order_id=order.id, status="COMPLETED").first()
        if existing:
            return existing
        refund = Refund(
            order_id=order.id,
            amount=_decimal(order.total),
            reason=reason,
            status="COMPLETED",
        )
        db.session.add(refund)
        return refund

    def _transition_payment_to_refunded(self, order: Order, actor_id=None, reason=""):
        payment = order.payment
        if payment is None:
            return None
        if (payment.status or "").upper() == "REFUNDED":
            return payment
        if (payment.status or "").upper() == "PAID":
            return payment.transition_to("REFUNDED", actor_id=actor_id, reason=reason)
        return None

    def _cancel_pending_payment(self, order: Order, actor_id=None, reason=""):
        payment = order.payment
        if payment is not None and payment.can_transition_to("CANCELLED"):
            payment.transition_to("CANCELLED", actor_id=actor_id, reason=reason)
        order.payment_status = "CANCELLED"

    def _free_delivery_assignment(self, order: Order):
        delivery = order.delivery
        if delivery is None:
            return
        delivery.status = "CANCELLED" if order.status == "CANCELLED" else "REFUNDED"
        agent = delivery.agent
        if agent is not None:
            has_open_delivery = (
                Delivery.query.filter(
                    Delivery.agent_id == agent.id,
                    Delivery.order_id != order.id,
                    Delivery.status.in_(("ASSIGNED", "OUT_FOR_DELIVERY", "PACKED")),
                ).first()
                is not None
            )
            agent.availability = not has_open_delivery

    def _audit(self, order, action, before, reason, reverse_stock, actor_id, initiated_by):
        if self.audit_service is None:
            return
        self.audit_service.log(
            actor_id,
            action,
            "Order",
            order.id,
            before=before,
            after={
                "status": order.status,
                "payment_status": order.payment_status,
                "reason": reason,
                "reverse_stock": reverse_stock,
                "initiated_by": initiated_by,
            },
            branch_id=order.branch_id,
            change_summary=f"Order #{order.order_number} {action.replace('_', ' ')}.",
        )
