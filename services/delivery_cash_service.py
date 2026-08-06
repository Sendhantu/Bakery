from decimal import Decimal, InvalidOperation

from exceptions import ValidationError
from models import DeliveryCashLedger, SalaryRecord, db
from clock import utcnow


LEDGER_INCREASE_ACTIONS = {"cod_collected"}
LEDGER_DECREASE_ACTIONS = {
    "cash_handover",
    "salary_deduction",
    "vendor_payout_deduction",
    "cash_adjustment",
}


class DeliveryCashService:
    def _decimal(self, value, label="amount"):
        try:
            amount = Decimal(str(value or 0)).quantize(Decimal("0.01"))
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise ValidationError(f"Please enter a valid {label}.") from exc
        if amount <= 0:
            raise ValidationError(f"{label.title()} must be greater than zero.")
        return amount

    def current_balance(self, agent_id):
        latest = (
            DeliveryCashLedger.query.filter_by(agent_id=agent_id)
            .order_by(DeliveryCashLedger.created_at.desc(), DeliveryCashLedger.id.desc())
            .first()
        )
        return Decimal(str(latest.balance_after or 0)) if latest else Decimal("0.00")

    def agent_balances(self, agent_ids):
        return {agent_id: self.current_balance(agent_id) for agent_id in agent_ids}

    def _record_entry(
        self,
        *,
        agent_id,
        action,
        amount,
        actor_id=None,
        order_id=None,
        payment_mode="CASH",
        recovery_method=None,
        notes="",
    ):
        amount = self._decimal(amount)
        balance = self.current_balance(agent_id)
        if action in LEDGER_INCREASE_ACTIONS:
            balance_after = balance + amount
        elif action in LEDGER_DECREASE_ACTIONS:
            if amount > balance:
                raise ValidationError("Amount cannot be greater than the rider cash balance.")
            balance_after = balance - amount
        else:
            raise ValidationError("Choose a valid cash ledger action.")

        entry = DeliveryCashLedger(
            agent_id=agent_id,
            order_id=order_id,
            action=action,
            amount=amount,
            balance_after=balance_after,
            payment_mode=(payment_mode or "CASH").strip().upper(),
            recovery_method=recovery_method,
            notes=(notes or "").strip() or None,
            recorded_by=actor_id,
        )
        db.session.add(entry)
        return entry

    def record_cod_collection(
        self,
        *,
        agent_id,
        order_id,
        amount,
        payment_mode="CASH",
        actor_id=None,
    ):
        payment_mode = (payment_mode or "CASH").strip().upper()
        if payment_mode != "CASH":
            return None
        return self._record_entry(
            agent_id=agent_id,
            order_id=order_id,
            action="cod_collected",
            amount=amount,
            payment_mode=payment_mode,
            actor_id=actor_id,
            notes="COD cash collected from customer.",
        )

    def record_handover(self, *, agent_id, amount, actor_id=None, notes=""):
        return self._record_entry(
            agent_id=agent_id,
            action="cash_handover",
            amount=amount,
            actor_id=actor_id,
            notes=notes or "Cash handed over to store.",
        )

    def record_recovery(
        self,
        *,
        agent,
        amount,
        recovery_method,
        actor_id=None,
        notes="",
    ):
        recovery_method = (recovery_method or "").strip().lower()
        if recovery_method not in {"salary_deduction", "vendor_payout_deduction"}:
            raise ValidationError("Choose salary deduction or vendor payout deduction.")
        if recovery_method == "salary_deduction" and not agent.user_id:
            raise ValidationError("Salary deduction requires an employee-linked rider account.")

        entry = self._record_entry(
            agent_id=agent.id,
            action=recovery_method,
            amount=amount,
            actor_id=actor_id,
            recovery_method=recovery_method,
            notes=notes or recovery_method.replace("_", " ").title(),
        )
        if recovery_method == "salary_deduction":
            today = utcnow().date()
            db.session.add(
                SalaryRecord(
                    user_id=agent.user_id,
                    branch_id=agent.branch_id,
                    period_start=today,
                    period_end=today,
                    amount=-entry.amount,
                    status="deducted",
                    notes=f"Delivery COD cash shortage recovery: {notes or 'cash not handed over'}",
                )
            )
        return entry
