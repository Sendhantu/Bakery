import json
from decimal import Decimal, InvalidOperation

from clock import utcnow
from exceptions import ValidationError
from models import Coupon, Order, db


POS_PAYMENT_METHODS = {"CASH", "CARD", "UPI", "SWIGGY", "ZOMATO", "OTHER"}
POS_FINAL_STATUSES = {"PLACED", "PREPARING", "READY_FOR_PICKUP", "DELIVERED"}


def _money(value):
    try:
        return Decimal(str(value or 0)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValidationError("Enter a valid payment amount.") from exc


def _payload_dict(raw_payload):
    if not raw_payload:
        return {}
    try:
        payload = json.loads(raw_payload)
    except (TypeError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


class PaymentService:
    def validate_coupon(self, code, subtotal, user=None):
        coupon_code = (code or "").strip().upper()
        coupon = Coupon.query.filter_by(code=coupon_code).first()
        if not coupon or not coupon.is_valid():
            return {"valid": False, "message": "Invalid or expired coupon."}

        subtotal_value = float(subtotal or 0)
        if subtotal_value < float(coupon.min_order_value):
            return {
                "valid": False,
                "message": f"Minimum order ₹{coupon.min_order_value} required.",
            }

        prior_order_count = 0
        prior_coupon_uses = 0
        if user and getattr(user, "is_authenticated", False):
            prior_order_count = Order.query.filter_by(user_id=user.id).count()
            prior_coupon_uses = Order.query.filter_by(
                user_id=user.id,
                coupon_code=coupon_code,
            ).count()

        eligibility_message = coupon.eligibility_message(prior_order_count)
        if eligibility_message:
            return {"valid": False, "message": eligibility_message}

        if prior_coupon_uses >= int(coupon.per_user_limit or 1):
            return {
                "valid": False,
                "message": "You have already used this coupon.",
            }

        if coupon.discount_type == "percentage":
            discount = round(subtotal_value * float(coupon.discount_value) / 100, 2)
        else:
            discount = float(coupon.discount_value)

        return {
            "valid": True,
            "discount": discount,
            "message": f"Coupon applied! You save ₹{discount:.0f}",
        }

    def confirm_counter_payment(
        self,
        order,
        *,
        amount_received,
        payment_method="CASH",
        actor_id=None,
        provider="manual_phone",
        transaction_reference="",
        final_status=None,
    ):
        """Mark a walk-in POS payment as received.

        The current provider is a phone/manual terminal. A future POS-machine
        webhook can call this same method after terminal authorization succeeds.
        """
        if order is None:
            raise ValidationError("Walk-in order not found.")
        if (order.channel or "").lower() != "counter":
            raise ValidationError("Only walk-in counter orders can use POS payment.")
        if (order.status or "").upper() in {"CANCELLED", "REFUNDED"}:
            raise ValidationError("This walk-in bill is already voided.")

        payment = order.payment
        if payment is None:
            raise ValidationError("No payment record exists for this walk-in order.")

        due = _money(order.total)
        received = _money(amount_received)
        if received < due:
            raise ValidationError("Amount received is less than the bill total.")

        method = (payment_method or order.payment_method or "CASH").strip().upper()
        if method not in POS_PAYMENT_METHODS:
            method = "OTHER"

        payload = _payload_dict(payment.gateway_payload)
        intended_status = (
            final_status
            or payload.get("intended_order_status")
            or order.status
            or "DELIVERED"
        )
        intended_status = (intended_status or "DELIVERED").strip().upper()
        if intended_status not in POS_FINAL_STATUSES:
            intended_status = "DELIVERED"

        change_due = (received - due).quantize(Decimal("0.01"))
        payment.method = method
        payment.amount = due
        payment.gateway_name = provider
        payment.transaction_id = (
            (transaction_reference or "").strip()
            or payment.transaction_id
            or f"POS-{order.id}-{utcnow().strftime('%Y%m%d%H%M%S')}"
        )
        payload.update(
            {
                "provider": provider,
                "source": "manual_pos_terminal",
                "amount_due": str(due),
                "amount_received": str(received),
                "change_due": str(change_due),
                "payment_method": method,
                "confirmed_at": utcnow().isoformat(),
                "confirmed_by": actor_id,
                "transaction_reference": payment.transaction_id,
                "intended_order_status": intended_status,
            }
        )
        payment.gateway_payload = json.dumps(payload, sort_keys=True)

        if (payment.status or "").upper() != "PAID":
            try:
                payment.transition_to(
                    "PAID",
                    actor_id=actor_id,
                    reason="manual_pos_amount_received",
                )
            except ValueError as exc:
                raise ValidationError(str(exc)) from exc

        previous_status = order.status
        order.payment_method = method
        order.payment_status = "PAID"
        if intended_status != (order.status or "").upper():
            order.status = intended_status
            order.mark_status_change()
            if intended_status == "DELIVERED":
                self._award_counter_loyalty(order)

        db.session.flush()
        return {
            "order": order,
            "payment": payment,
            "amount_due": due,
            "amount_received": received,
            "change_due": change_due,
            "previous_status": previous_status,
            "new_status": order.status,
        }

    def _award_counter_loyalty(self, order):
        try:
            from bootstrap import get_container

            get_container().loyalty_service.award_order_points(order)
        except Exception:
            return 0
