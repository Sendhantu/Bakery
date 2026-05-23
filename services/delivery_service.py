from datetime import datetime
from decimal import Decimal, InvalidOperation

from exceptions import ValidationError
from models import Payment, db
from repositories import OrderRepository


class DeliveryService:
    def __init__(self, order_repository=None, audit_service=None):
        self.order_repository = order_repository or OrderRepository()
        self.audit_service = audit_service

    def collect_cod_payment(self, order_id, amount_received, payment_mode="CASH", actor_id=None, expected_version=None):
        order = self.order_repository.get_or_404(order_id)
        # optimistic check if caller provided expected_version
        from utils.optimistic import assert_version
        assert_version(order, expected_version, entity_name='Order')
        if (order.payment_method or "").upper() != "COD":
            raise ValidationError("This order is not marked for cash on delivery.")
        if (order.payment_status or "").upper() == "PAID":
            raise ValidationError("COD payment has already been collected for this order.")

        try:
            amount = Decimal(str(amount_received or order.total or 0))
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise ValidationError("Please enter a valid collected amount.") from exc

        total_due = Decimal(str(order.total or 0))
        if amount < total_due:
            raise ValidationError("Collected amount cannot be less than the order total.")

        with db.session.begin_nested():
            payment = order.payment
            if payment is None:
                payment = Payment(order_id=order.id, amount=total_due)
                db.session.add(payment)

            payment.amount = amount
            payment.method = f"COD_{(payment_mode or 'CASH').strip().upper()}"
            payment.transaction_id = payment.transaction_id or f"COD-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
            payment.transition_to(
                "PAID",
                actor_id=actor_id,
                reason="cod_collection",
            )
            order.mark_status_change()
            if self.audit_service is not None:
                self.audit_service.record(
                    "cod_payment_collected",
                    "Order",
                    order.id,
                    actor_id=actor_id,
                    branch_id=order.branch_id,
                    metadata={"amount": float(amount), "payment_mode": payment_mode},
                    change_summary=f"COD collected via {payment_mode}",
                )
        db.session.commit()
        return order
