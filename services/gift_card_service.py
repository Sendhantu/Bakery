from decimal import Decimal

from clock import utcnow
from exceptions import ValidationError
from models import (
    FinancialCategory,
    FinancialTransaction,
    GiftCard,
    GiftCardTransaction,
    db,
)
from models.gift_card import generate_gift_card_code


class GiftCardService:
    MIN_AMOUNT = Decimal("50.00")
    MAX_AMOUNT = Decimal("50000.00")

    def ensure_finance_category(self):
        category = FinancialCategory.query.filter_by(code="gift_card_liability").first()
        if category is None:
            category = FinancialCategory(
                code="gift_card_liability",
                label="Gift Card Liability",
                transaction_type="liability",
                is_system=True,
                is_active=True,
                sort_order=15,
            )
            db.session.add(category)
            db.session.flush()
        return category

    def issue(
        self,
        *,
        amount,
        purchased_by_user_id=None,
        recipient_email=None,
        message=None,
        actor_id=None,
        reason="gift_card_purchase",
    ):
        amount = self._amount(amount)
        if amount < self.MIN_AMOUNT:
            raise ValidationError("Gift card amount must be at least ₹50.")
        if amount > self.MAX_AMOUNT:
            raise ValidationError("Gift card amount is too high.")

        code = self._unique_code()
        card = GiftCard(
            code=code,
            initial_value=amount,
            current_balance=amount,
            status="active",
            purchased_by_user_id=purchased_by_user_id,
            recipient_email=(recipient_email or "").strip() or None,
            message=(message or "").strip() or None,
            issued_at=utcnow(),
        )
        db.session.add(card)
        db.session.flush()
        db.session.add(
            GiftCardTransaction(
                gift_card_id=card.id,
                amount_change=amount,
                transaction_type="issued",
                reason=reason,
                created_by=actor_id,
            )
        )
        self.record_liability(card, amount, actor_id=actor_id)
        return card

    def record_liability(self, card, amount, actor_id=None):
        category = self.ensure_finance_category()
        txn = FinancialTransaction(
            transaction_type="liability",
            category_id=category.id,
            amount=amount,
            tax_amount=Decimal("0"),
            description=f"Gift card issued {card.code}",
            counterparty=card.recipient_email or None,
            is_auto_generated=True,
            idempotency_key=f"gift-card-issued-{card.id}",
            created_by=actor_id,
        )
        db.session.add(txn)
        return txn

    def preview_redemption(self, code, payable_amount, *, lock=False):
        card = self.get_active_card(code, lock=lock)
        payable = max(Decimal("0"), self._amount(payable_amount))
        amount = min(Decimal(str(card.current_balance or 0)), payable)
        if amount <= 0:
            raise ValidationError("This gift card cannot be applied to this order.")
        return {"gift_card": card, "amount": amount}

    def redeem(self, code, order, payable_amount, *, actor_id=None):
        preview = self.preview_redemption(code, payable_amount, lock=True)
        card = preview["gift_card"]
        amount = preview["amount"]
        current_balance = Decimal(str(card.current_balance or 0))
        if amount > current_balance:
            raise ValidationError("Gift card balance is too low.")
        card.current_balance = (current_balance - amount).quantize(Decimal("0.01"))
        if card.current_balance == Decimal("0.00"):
            card.status = "redeemed"
        db.session.add(
            GiftCardTransaction(
                gift_card_id=card.id,
                order_id=order.id if order else None,
                amount_change=-amount,
                transaction_type="redeemed",
                reason=f"Redeemed against order #{order.order_number}",
                created_by=actor_id,
            )
        )
        return {"gift_card": card, "amount": amount}

    def manual_adjust(self, card, amount_change, *, reason, actor_id=None):
        if not reason or not reason.strip():
            raise ValidationError("A reason is required for gift card adjustments.")
        change = self._amount(amount_change)
        if change == 0:
            raise ValidationError("Adjustment amount cannot be zero.")
        new_balance = Decimal(str(card.current_balance or 0)) + change
        if new_balance < 0:
            raise ValidationError("Gift card balance cannot go below zero.")
        card.current_balance = new_balance.quantize(Decimal("0.01"))
        if card.status != "cancelled":
            card.status = "redeemed" if card.current_balance == 0 else "active"
        db.session.add(
            GiftCardTransaction(
                gift_card_id=card.id,
                amount_change=change,
                transaction_type="manual_adjustment",
                reason=reason.strip(),
                created_by=actor_id,
            )
        )
        return card

    def cancel(self, card, *, reason, actor_id=None):
        if not reason or not reason.strip():
            raise ValidationError("A reason is required to cancel a gift card.")
        if card.status == "cancelled":
            return card
        balance = Decimal(str(card.current_balance or 0))
        card.status = "cancelled"
        card.current_balance = Decimal("0.00")
        if balance:
            db.session.add(
                GiftCardTransaction(
                    gift_card_id=card.id,
                    amount_change=-balance,
                    transaction_type="manual_adjustment",
                    reason=f"Cancelled: {reason.strip()}",
                    created_by=actor_id,
                )
            )
        return card

    def outstanding_liability(self):
        total = db.session.query(
            db.func.coalesce(db.func.sum(GiftCard.current_balance), 0)
        ).filter(GiftCard.status == "active").scalar() or Decimal("0")
        return Decimal(str(total)).quantize(Decimal("0.01"))

    def get_active_card(self, code, *, lock=False):
        normalized = (code or "").strip().upper()
        if not normalized:
            raise ValidationError("Enter a gift card code.")
        query = GiftCard.query.filter_by(code=normalized)
        if lock:
            query = query.with_for_update()
        card = query.first()
        if card is None:
            raise ValidationError("Gift card was not found.")
        if card.status != "active":
            raise ValidationError("Gift card is not active.")
        if card.expires_at and card.expires_at <= utcnow():
            card.status = "expired"
            raise ValidationError("Gift card has expired.")
        if Decimal(str(card.current_balance or 0)) <= 0:
            raise ValidationError("Gift card has no remaining balance.")
        return card

    def _unique_code(self):
        for _ in range(10):
            code = generate_gift_card_code()
            if GiftCard.query.filter_by(code=code).first() is None:
                return code
        raise ValidationError("Could not generate a unique gift card code.")

    def _amount(self, value):
        try:
            return Decimal(str(value or 0)).quantize(Decimal("0.01"))
        except Exception as exc:
            raise ValidationError("Enter a valid amount.") from exc
