import json
import re
import secrets
from decimal import Decimal, InvalidOperation

from clock import utcnow
from exceptions import ValidationError
from models import Coupon, Order, Payment, PosPaymentTransaction, db


POS_PAYMENT_METHODS = {"CASH", "CARD", "UPI", "SWIGGY", "ZOMATO", "OTHER"}
POS_MVP_PAYMENT_METHODS = {
    "CASH",
    "UPI",
    "CREDIT_CARD",
    "DEBIT_CARD",
    "BANK_TRANSFER",
    "OTHER",
}
POS_FINAL_STATUSES = {"PLACED", "PREPARING", "READY_FOR_PICKUP", "DELIVERED"}


def _money(value):
    try:
        return Decimal(str(value or 0)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValidationError("Enter a valid payment amount.") from exc


def _positive_money(value, *, field_name="amount"):
    amount = _money(value)
    if amount <= 0:
        raise ValidationError(f"{field_name.title()} must be greater than zero.")
    return amount


def _clean_reference(value, max_length=120):
    value = (value or "").strip()
    return re.sub(r"[^A-Za-z0-9 ._:/#-]", "", value)[:max_length]


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

    def record_pos_mvp_payment(
        self,
        *,
        amount,
        payment_method,
        cashier_id,
        branch_id=None,
        order_id=None,
        order_number="",
        cash_received=None,
        transaction_reference="",
        upi_app="",
        card_last4="",
        card_type="",
        bank_name="",
        payment_date="",
        other_note="",
        notes="",
        idempotency_key="",
        transaction_limit=None,
    ):
        idempotency_key = (idempotency_key or "").strip()
        if not idempotency_key:
            raise ValidationError("Missing payment request identifier. Please refresh and try again.")
        existing = PosPaymentTransaction.query.filter_by(
            idempotency_key=idempotency_key
        ).first()
        if existing:
            return existing, False

        method = (payment_method or "").strip().upper()
        if method not in POS_MVP_PAYMENT_METHODS:
            raise ValidationError("Select a supported payment method.")

        order = None
        if order_id:
            order = db.session.get(Order, int(order_id))
        elif order_number:
            order = Order.query.filter_by(order_number=(order_number or "").strip()).first()
        if order is not None and (order.payment_status or "").upper() == "PAID":
            raise ValidationError("The selected order is already paid.")

        payable = _positive_money(order.total if order is not None else amount)
        limit = _money(transaction_limit or 100000)
        if payable > limit:
            raise ValidationError(f"Amount cannot exceed ₹{limit:.2f}.")

        received = None
        change = None
        if method == "CASH":
            received = _positive_money(cash_received, field_name="cash received")
            if received < payable:
                raise ValidationError("Cash received is less than the amount payable.")
            change = (received - payable).quantize(Decimal("0.01"))

        if method == "OTHER" and not (other_note or "").strip():
            raise ValidationError("Add a short note for Other payment method.")

        details = {
            "upi_app": _clean_reference(upi_app, 40),
            "card_last4": re.sub(r"\D+", "", card_last4 or "")[-4:],
            "card_type": _clean_reference(card_type, 40),
            "bank_name": _clean_reference(bank_name, 80),
            "payment_date": _clean_reference(payment_date, 20),
            "other_note": _clean_reference(other_note, 160),
        }
        if card_last4 and len(details["card_last4"]) not in {0, 4}:
            raise ValidationError("Card last four digits must contain four digits.")

        payment = order.payment if order is not None else None
        if order is not None and payment is None:
            payment = Payment(
                order_id=order.id,
                amount=payable,
                status="PENDING",
                method=method,
            )
            db.session.add(payment)
            db.session.flush()

        transaction = PosPaymentTransaction(
            transaction_id=f"POS-{utcnow().strftime('%Y%m%d')}-{secrets.token_hex(4).upper()}",
            order_id=order.id if order is not None else None,
            payment_id=payment.id if payment is not None else None,
            amount=payable,
            currency="INR",
            payment_method=method,
            payment_status="COMPLETED",
            cash_received=received,
            change_returned=change,
            transaction_reference=_clean_reference(transaction_reference),
            method_details_json=json.dumps(
                {key: value for key, value in details.items() if value},
                sort_keys=True,
            ),
            notes=_clean_reference(notes, 300),
            cashier_id=cashier_id,
            branch_id=branch_id or getattr(order, "branch_id", None),
            idempotency_key=idempotency_key,
        )
        db.session.add(transaction)
        db.session.flush()

        if payment is not None:
            payment.amount = payable
            payment.method = method
            payment.transaction_id = transaction.transaction_id
            payment.gateway_name = "manual_pos_mvp"
            payment.gateway_payload = json.dumps(
                {
                    "source": "manual_pos_mvp",
                    "pos_transaction_id": transaction.transaction_id,
                    "transaction_reference": transaction.transaction_reference,
                    "cash_received": str(received) if received is not None else None,
                    "change_returned": str(change) if change is not None else None,
                },
                sort_keys=True,
            )
            if (payment.status or "").upper() != "PAID":
                payment.transition_to(
                    "PAID",
                    actor_id=cashier_id,
                    reason="manual_pos_mvp_payment_confirmed",
                )
        if order is not None:
            order.payment_method = method
            order.payment_status = "PAID"
            order.mark_status_change()

        return transaction, True

    def _award_counter_loyalty(self, order):
        try:
            from bootstrap import get_container

            get_container().loyalty_service.award_order_points(order)
        except Exception:
            return 0
