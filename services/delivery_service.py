from datetime import datetime
from decimal import Decimal, InvalidOperation

from exceptions import ValidationError
from models import Payment, db
from repositories import OrderRepository


class DeliveryService:
    def __init__(self, order_repository=None):
        self.order_repository = order_repository or OrderRepository()

    def collect_cod_payment(self, order_id, amount_received, payment_mode="CASH"):
        order = self.order_repository.get_or_404(order_id)
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

        payment = order.payment
        if payment is None:
            payment = Payment(order_id=order.id, amount=total_due)
            db.session.add(payment)

        payment.amount = amount
        payment.status = "PAID"
        payment.method = f"COD_{(payment_mode or 'CASH').strip().upper()}"
        payment.transaction_id = f"COD-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
        order.payment_status = "PAID"
        order.updated_at = datetime.utcnow()
        db.session.commit()
        return order
