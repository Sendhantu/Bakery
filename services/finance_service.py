from __future__ import annotations

from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Tuple

from dateutil.relativedelta import relativedelta
from flask import current_app
from sqlalchemy import func

from clock import utcnow
from models import (
    Branch,
    FinancialCategory,
    FinancialTransaction,
    Order,
    Product,
    ProductMaterial,
    RawMaterial,
    StockMovement,
    TaxRate,
    TaxRecord,
    db,
)
from services.analytics_service import (
    REVENUE_ORDER_STATUSES,
    REVENUE_PAYMENT_STATUSES,
    _product_sales_query,
    _revenue_order_filters,
    period_bounds,
)
from services.invoice_service import InvoiceService


DEFAULT_CATEGORIES = [
    ("sales", "Sales", "income", 10),
    ("raw_material_purchase", "Raw Material Purchase", "expense", 20),
    ("rent", "Rent", "expense", 30),
    ("utilities", "Utilities", "expense", 40),
    ("salary", "Salary", "expense", 50),
    ("other_income", "Other Income", "income", 60),
    ("other_expense", "Other Expense", "expense", 70),
]


class FinanceService:
    def ensure_default_categories(self):
        created = False
        for code, label, txn_type, sort_order in DEFAULT_CATEGORIES:
            existing = FinancialCategory.query.filter_by(code=code).first()
            if existing:
                continue
            db.session.add(
                FinancialCategory(
                    code=code,
                    label=label,
                    transaction_type=txn_type,
                    is_system=True,
                    is_active=True,
                    sort_order=sort_order,
                )
            )
            created = True
        if created:
            db.session.flush()

    def get_category(self, code: str) -> Optional[FinancialCategory]:
        return FinancialCategory.query.filter_by(code=code, is_active=True).first()

    def active_categories(self, transaction_type: Optional[str] = None):
        query = FinancialCategory.query.filter_by(is_active=True).order_by(
            FinancialCategory.sort_order.asc(), FinancialCategory.label.asc()
        )
        if transaction_type:
            query = query.filter(
                (FinancialCategory.transaction_type == transaction_type)
                | (FinancialCategory.transaction_type == "either")
            )
        return query.all()

    def resolve_sales_tax_rate(self, order: Order) -> Decimal:
        stored = Decimal(str(order.gst_rate or 0))
        if stored > 0:
            return stored
        active_rate = (
            TaxRate.query.filter_by(is_active=True, applies_to="sales")
            .order_by(TaxRate.effective_from.desc())
            .first()
        )
        if active_rate:
            return Decimal(str(active_rate.rate_percent or 0))
        return Decimal("5")

    def extract_gst_from_inclusive(self, inclusive_amount: Decimal, rate_percent: Decimal) -> Decimal:
        """Extract GST embedded in a tax-inclusive shelf price."""
        inclusive = Decimal(str(inclusive_amount or 0))
        rate = Decimal(str(rate_percent or 0))
        if inclusive <= 0 or rate <= 0:
            return Decimal("0")
        base = inclusive / (Decimal("1") + rate / Decimal("100"))
        return (inclusive - base).quantize(Decimal("0.01"))

    def compute_order_gst_amount(self, order: Order) -> Decimal:
        """Reuse invoice taxable base, then treat shelf prices as tax-inclusive."""
        breakdown = InvoiceService(storage_service=None).calculate_gst_breakdown(order)
        inclusive_taxable = Decimal(str(breakdown["taxable_amount"])) + Decimal(
            str(breakdown["gst_amount"])
        )
        rate = Decimal(str(breakdown["gst_rate"]))
        if inclusive_taxable <= 0:
            return Decimal("0")
        return self.extract_gst_from_inclusive(inclusive_taxable, rate)

    def _branch_context(self, branch_id: Optional[int]) -> Tuple[Optional[int], str]:
        if branch_id:
            branch = db.session.get(Branch, branch_id)
            if branch:
                return branch.id, branch.name
        default_id = current_app.config.get("DEFAULT_BRANCH_ID")
        if default_id:
            branch = db.session.get(Branch, default_id)
            if branch:
                return branch.id, branch.name
        store = current_app.config.get("STORE_DETAILS") or {}
        return branch_id, store.get("name") or current_app.config.get("BAKERY_NAME", "Main Store")

    def record_sale_from_order(self, order: Order, actor_id: Optional[int] = None) -> Optional[FinancialTransaction]:
        if order is None:
            return None
        idempotency_key = f"sale-order-{order.id}"
        existing = FinancialTransaction.query.filter_by(idempotency_key=idempotency_key).first()
        if existing:
            return existing

        category = self.get_category("sales")
        if category is None:
            self.ensure_default_categories()
            category = self.get_category("sales")
        if category is None:
            return None

        branch_id, store_location = self._branch_context(order.branch_id)
        gst_amount = self.compute_order_gst_amount(order)
        txn = FinancialTransaction(
            transaction_type="income",
            category_id=category.id,
            amount=Decimal(str(order.total or 0)),
            tax_amount=gst_amount,
            description=f"Sale for order #{order.order_number}",
            counterparty=order.customer.name if order.customer else None,
            reference_order_id=order.id,
            branch_id=branch_id,
            store_location=store_location,
            is_auto_generated=True,
            idempotency_key=idempotency_key,
            created_by=actor_id,
        )
        db.session.add(txn)
        self._audit_transaction(txn, actor_id, created=True)
        return txn

    def _audit_transaction(self, txn, actor_id, created=True):
        try:
            from bootstrap import get_container

            action = "financial_transaction_created" if created else "financial_transaction_updated"
            get_container().audit_service.log(
                actor_id,
                action,
                "FinancialTransaction",
                txn.id,
                before=None if created else {"transaction_id": txn.id},
                after={
                    "transaction_type": txn.transaction_type,
                    "category_id": txn.category_id,
                    "reference_order_id": txn.reference_order_id,
                    "reference_stock_movement_id": txn.reference_stock_movement_id,
                    "amount": txn.amount,
                    "tax_amount": txn.tax_amount,
                    "description": txn.description,
                    "counterparty": txn.counterparty,
                    "is_auto_generated": txn.is_auto_generated,
                },
                branch_id=txn.branch_id,
                change_summary=f"Financial transaction recorded ({txn.transaction_type})",
            )
        except Exception:
            pass

    def create_manual_transaction(
        self,
        *,
        transaction_type: str,
        category_id: int,
        amount: Decimal,
        tax_amount: Optional[Decimal] = None,
        description: str = "",
        counterparty: str = "",
        branch_id: Optional[int] = None,
        tds_withheld: Optional[Decimal] = None,
        created_by: Optional[int] = None,
    ) -> FinancialTransaction:
        branch_id, store_location = self._branch_context(branch_id)
        txn = FinancialTransaction(
            transaction_type=(transaction_type or "").strip().lower(),
            category_id=category_id,
            amount=Decimal(str(amount)),
            tax_amount=Decimal(str(tax_amount)) if tax_amount is not None else None,
            description=(description or "").strip() or None,
            counterparty=(counterparty or "").strip() or None,
            branch_id=branch_id,
            store_location=store_location,
            tds_withheld=Decimal(str(tds_withheld)) if tds_withheld is not None else None,
            created_by=created_by,
        )
        db.session.add(txn)
        self._audit_transaction(txn, created_by, created=True)
        return txn

    def log_restock_expense(
        self,
        movement: StockMovement,
        *,
        amount: Decimal,
        tax_amount: Optional[Decimal] = None,
        counterparty: str = "",
        created_by: Optional[int] = None,
    ) -> FinancialTransaction:
        idempotency_key = f"restock-movement-{movement.id}"
        existing = FinancialTransaction.query.filter_by(idempotency_key=idempotency_key).first()
        if existing:
            return existing

        category = self.get_category("raw_material_purchase")
        if category is None:
            self.ensure_default_categories()
            category = self.get_category("raw_material_purchase")

        material = movement.raw_material
        branch_id, store_location = self._branch_context(material.branch_id if material else None)
        description = (
            f"Restock {material.name} (+{movement.change_amount} {material.unit})"
            if material
            else f"Restock movement #{movement.id}"
        )
        txn = FinancialTransaction(
            transaction_type="expense",
            category_id=category.id,
            amount=Decimal(str(amount)),
            tax_amount=Decimal(str(tax_amount)) if tax_amount is not None else None,
            description=description,
            counterparty=(counterparty or (material.supplier if material else "")) or None,
            reference_stock_movement_id=movement.id,
            branch_id=branch_id,
            store_location=store_location,
            is_auto_generated=False,
            idempotency_key=idempotency_key,
            created_by=created_by,
        )
        db.session.add(txn)
        self._audit_transaction(txn, created_by, created=True)
        return txn

    def suggest_restock_expense_amount(self, movement: StockMovement) -> Decimal:
        material = movement.raw_material
        if material is None:
            return Decimal("0")
        qty = Decimal(str(movement.change_amount or 0))
        unit_cost = Decimal(str(material.cost_per_unit or 0))
        return (qty * unit_cost).quantize(Decimal("0.01"))

    def _transactions_in_period(self, start: datetime, end: datetime, transaction_type: Optional[str] = None):
        query = FinancialTransaction.query.filter(
            FinancialTransaction.created_at >= start,
            FinancialTransaction.created_at < end,
        )
        if transaction_type:
            query = query.filter_by(transaction_type=transaction_type)
        return query.all()

    def _sum_amounts(self, transactions: List[FinancialTransaction]) -> Decimal:
        total = Decimal("0")
        for txn in transactions:
            total += Decimal(str(txn.amount or 0))
        return total.quantize(Decimal("0.01"))

    def _sum_tax(self, transactions: List[FinancialTransaction]) -> Decimal:
        total = Decimal("0")
        for txn in transactions:
            if txn.tax_amount is not None:
                total += Decimal(str(txn.tax_amount))
        return total.quantize(Decimal("0.01"))

    def _sum_tds(self, transactions: List[FinancialTransaction]) -> Decimal:
        total = Decimal("0")
        for txn in transactions:
            if txn.tds_withheld is not None:
                total += Decimal(str(txn.tds_withheld))
        return total.quantize(Decimal("0.01"))

    def profit_and_loss(self, start_date=None, end_date=None) -> Dict[str, Any]:
        start, end = period_bounds("custom", start_date=start_date, end_date=end_date)
        income_txns = self._transactions_in_period(start, end, "income")
        expense_txns = self._transactions_in_period(start, end, "expense")
        income = self._sum_amounts(income_txns)
        expenses = self._sum_amounts(expense_txns)
        net = (income - expenses).quantize(Decimal("0.01"))
        return {
            "start": start,
            "end": end,
            "income": income,
            "expenses": expenses,
            "net_profit": net,
            "income_transactions": income_txns,
            "expense_transactions": expense_txns,
        }

    def product_ledger(self, start_date=None, end_date=None) -> List[Dict[str, Any]]:
        start, end = period_bounds("custom", start_date=start_date, end_date=end_date)
        sales_rows = _product_sales_query(start, end).all()
        cogs_by_product: Dict[int, Decimal] = {}

        recipe_rows = (
            db.session.query(ProductMaterial, RawMaterial)
            .join(RawMaterial, RawMaterial.id == ProductMaterial.raw_material_id)
            .all()
        )
        unit_cogs = {}
        for recipe, material in recipe_rows:
            unit_cogs[recipe.product_id] = unit_cogs.get(recipe.product_id, Decimal("0")) + (
                Decimal(str(recipe.quantity_required or 0)) * Decimal(str(material.cost_per_unit or 0))
            )

        ledger = []
        for row in sales_rows:
            product_id = row.product_id
            units = Decimal(str(row.units_sold or 0))
            revenue = Decimal(str(row.revenue or 0))
            cogs = (unit_cogs.get(product_id, Decimal("0")) * units).quantize(Decimal("0.01"))
            ledger.append(
                {
                    "product_id": product_id,
                    "product_name": row.product_name,
                    "units_sold": int(units),
                    "revenue": revenue,
                    "cogs": cogs,
                    "gross_profit": (revenue - cogs).quantize(Decimal("0.01")),
                }
            )
        return sorted(ledger, key=lambda item: item["revenue"], reverse=True)

    def store_ledger(self, start_date=None, end_date=None) -> List[Dict[str, Any]]:
        start, end = period_bounds("custom", start_date=start_date, end_date=end_date)
        txns = self._transactions_in_period(start, end)
        by_store: Dict[str, Dict[str, Decimal]] = {}

        for txn in txns:
            key = txn.store_location or "Unassigned"
            bucket = by_store.setdefault(
                key,
                {"store": key, "income": Decimal("0"), "expenses": Decimal("0"), "branch_id": txn.branch_id},
            )
            amount = Decimal(str(txn.amount or 0))
            if txn.transaction_type == "income":
                bucket["income"] += amount
            else:
                bucket["expenses"] += amount

        rows = []
        for bucket in by_store.values():
            rows.append(
                {
                    **bucket,
                    "income": bucket["income"].quantize(Decimal("0.01")),
                    "expenses": bucket["expenses"].quantize(Decimal("0.01")),
                    "net": (bucket["income"] - bucket["expenses"]).quantize(Decimal("0.01")),
                }
            )
        return sorted(rows, key=lambda item: item["store"])

    def gst_summary(self, start_date=None, end_date=None) -> Dict[str, Any]:
        start, end = period_bounds("custom", start_date=start_date, end_date=end_date)
        income_txns = self._transactions_in_period(start, end, "income")
        expense_txns = self._transactions_in_period(start, end, "expense")
        gst_collected = self._sum_tax(income_txns)
        gst_paid = self._sum_tax(expense_txns)
        net_liability = (gst_collected - gst_paid).quantize(Decimal("0.01"))
        return {
            "start": start,
            "end": end,
            "gst_collected": gst_collected,
            "gst_paid": gst_paid,
            "net_gst_liability": net_liability,
        }

    def tds_summary(self, start_date=None, end_date=None) -> Dict[str, Any]:
        start, end = period_bounds("custom", start_date=start_date, end_date=end_date)
        expense_txns = self._transactions_in_period(start, end, "expense")
        total_tds = self._sum_tds(expense_txns)
        vendor_rows = [
            {
                "counterparty": txn.counterparty or "Unspecified vendor",
                "amount": Decimal(str(txn.amount or 0)),
                "tds_withheld": Decimal(str(txn.tds_withheld or 0)),
                "created_at": txn.created_at,
            }
            for txn in expense_txns
            if txn.tds_withheld and Decimal(str(txn.tds_withheld)) > 0
        ]
        return {
            "start": start,
            "end": end,
            "tds_withheld": total_tds,
            "vendor_payments_tracked": len(vendor_rows) > 0,
            "rows": vendor_rows,
            "placeholder_note": (
                "Vendor payment tracking is limited to manually entered expense transactions with TDS."
                if not vendor_rows
                else ""
            ),
        }

    def save_tax_record(
        self,
        period_type: str,
        start_date,
        end_date,
        admin_notes: str = "",
    ) -> TaxRecord:
        gst = self.gst_summary(start_date=start_date, end_date=end_date)
        tds = self.tds_summary(start_date=start_date, end_date=end_date)
        period_start = _as_date(start_date)
        period_end = _as_date(end_date)
        record = TaxRecord.query.filter_by(
            period_type=period_type,
            period_start=period_start,
            period_end=period_end,
        ).first()
        if record is None:
            record = TaxRecord(
                period_type=period_type,
                period_start=period_start,
                period_end=period_end,
            )
            db.session.add(record)
        record.gst_collected = gst["gst_collected"]
        record.gst_paid = gst["gst_paid"]
        record.net_gst_liability = gst["net_gst_liability"]
        record.tds_withheld = tds["tds_withheld"]
        record.admin_adjustment_notes = (admin_notes or "").strip() or record.admin_adjustment_notes
        record.computed_at = utcnow()
        return record

    def recent_transactions(self, limit=50):
        return (
            FinancialTransaction.query.order_by(FinancialTransaction.created_at.desc())
            .limit(limit)
            .all()
        )


def _as_date(value) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, str):
        return datetime.strptime(value, "%Y-%m-%d").date()
    raise ValueError("Expected a date value.")


def maybe_record_sale_on_payment(payment, actor_id=None):
    """Hook for Payment.transition_to(PAID) — idempotent sale income row."""
    if payment is None or (payment.status or "").upper() != "PAID":
        return None
    order = payment.order
    if order is None and payment.order_id:
        order = db.session.get(Order, payment.order_id)
    if order is None:
        return None
    try:
        service = FinanceService()
        service.ensure_default_categories()
        return service.record_sale_from_order(order, actor_id=actor_id)
    except Exception:
        current_app.logger.exception("finance_sale_record_failed order_id=%s", payment.order_id)
        return None
