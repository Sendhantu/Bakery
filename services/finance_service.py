from __future__ import annotations

from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Tuple

from dateutil.relativedelta import relativedelta
from flask import current_app
from sqlalchemy import func, or_

from clock import utcnow
from models import (
    Branch,
    FinancialCategory,
    FinancialTransaction,
    GST_ECOMMERCE_OPERATOR_BY_SOURCE,
    GST_ECOMMERCE_ORDER_SOURCES,
    GST_LIABILITY_BAKERY,
    GST_LIABILITY_ECOMMERCE_OPERATOR,
    GST_ORDER_SOURCE_COUNTER_TAKEAWAY,
    GST_ORDER_SOURCE_COUNTER_DINE_IN,
    GST_ORDER_SOURCE_DIRECT_WEB_DELIVERY,
    GST_ORDER_SOURCE_DIRECT_WEB_PICKUP,
    GST_ORDER_SOURCE_ECOMMERCE_SWIGGY,
    GST_ORDER_SOURCE_ECOMMERCE_ZOMATO,
    GST_ORDER_SOURCE_LABELS,
    GST_ORDER_SOURCE_VALUES,
    GST_RETURN_ECOMMERCE_9_5,
    GST_RETURN_OUTWARD_SUPPLIES,
    GST_SUPPLY_RESTAURANT_SERVICE,
    Order,
    Product,
    ProductMaterial,
    RawMaterial,
    StockMovement,
    TDS_NO_PAN_RATE,
    TDS_PAYMENT_TYPE_CONFIG,
    TDS_PAYMENT_TYPE_NONE,
    TaxRate,
    TaxRecord,
    db,
)
from services.analytics_service import (
    PERIOD_LABELS,
    REVENUE_ORDER_STATUSES,
    REVENUE_PAYMENT_STATUSES,
    _product_sales_query,
    _revenue_order_filters,
    analytics_payload,
    period_bounds,
    total_revenue,
)
from services.invoice_service import InvoiceService


DEFAULT_CATEGORIES = [
    ("sales", "Sales", "income", 10),
    ("gift_card_liability", "Gift Card Liability", "liability", 15),
    ("raw_material_purchase", "Raw Material Purchase", "expense", 20),
    ("rent", "Rent", "expense", 30),
    ("utilities", "Utilities", "expense", 40),
    ("salary", "Salary", "expense", 50),
    ("other_income", "Other Income", "income", 60),
    ("refund", "Refunds", "expense", 65),
    ("other_expense", "Other Expense", "expense", 70),
]

FINANCE_PERIODS = {"day", "week", "month", "year", "financial_year", "custom"}
PERIOD_ALIASES = {
    "today": "day",
    "fy": "financial_year",
    "financial-year": "financial_year",
}
MONEY_QUANT = Decimal("0.01")


def financial_year_bounds(now=None):
    """Indian financial year: 1 April through 31 March."""
    current = (now or utcnow()).date()
    if current.month >= 4:
        start = date(current.year, 4, 1)
        end = date(current.year + 1, 3, 31)
    else:
        start = date(current.year - 1, 4, 1)
        end = date(current.year, 3, 31)
    return start, end


def _money(value) -> Decimal:
    return Decimal(str(value or 0)).quantize(MONEY_QUANT)


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

    def resolve_active_sales_tax_rate(self, as_of=None) -> Decimal:
        as_of_date = as_of.date() if isinstance(as_of, datetime) else as_of
        as_of_date = as_of_date or utcnow().date()
        active_rate = (
            TaxRate.query.filter(
                TaxRate.is_active == True,
                TaxRate.applies_to == "sales",
                TaxRate.effective_from <= as_of_date,
                or_(TaxRate.effective_to.is_(None), TaxRate.effective_to >= as_of_date),
            )
            .order_by(TaxRate.effective_from.desc())
            .first()
        )
        if active_rate:
            return Decimal(str(active_rate.rate_percent or 0))
        return Decimal("5")

    def resolve_sales_tax_rate(self, order: Order) -> Decimal:
        stored = Decimal(str(order.gst_rate or 0))
        if stored > 0:
            return stored
        return self.resolve_active_sales_tax_rate(getattr(order, "placed_at", None))

    def taxable_sales_amount(
        self,
        subtotal: Decimal,
        discount: Decimal = Decimal("0"),
        loyalty_discount: Decimal = Decimal("0"),
    ) -> Decimal:
        taxable = (
            Decimal(str(subtotal or 0))
            - Decimal(str(discount or 0))
            - Decimal(str(loyalty_discount or 0))
        )
        return max(taxable, Decimal("0")).quantize(Decimal("0.01"))

    def calculate_sales_gst(
        self,
        subtotal: Decimal,
        *,
        discount: Decimal = Decimal("0"),
        loyalty_discount: Decimal = Decimal("0"),
        rate_percent: Decimal | None = None,
    ) -> Dict[str, Decimal]:
        """Calculate output GST added on top of product prices at checkout."""
        rate = (
            Decimal(str(rate_percent))
            if rate_percent is not None
            else self.resolve_active_sales_tax_rate()
        )
        taxable = self.taxable_sales_amount(subtotal, discount, loyalty_discount)
        gst_amount = (taxable * rate / Decimal("100")).quantize(Decimal("0.01"))
        cgst_amount = (gst_amount / Decimal("2")).quantize(Decimal("0.01"))
        sgst_amount = (gst_amount - cgst_amount).quantize(Decimal("0.01"))
        return {
            "taxable_amount": taxable,
            "gst_rate": rate,
            "gst_amount": gst_amount,
            "cgst_amount": cgst_amount,
            "sgst_amount": sgst_amount,
        }

    def normalize_gst_order_source(
        self,
        value=None,
        *,
        channel="online",
        source=None,
        fulfillment_type="DELIVERY",
    ) -> str:
        explicit = (value or "").strip().upper()
        if explicit in GST_ORDER_SOURCE_VALUES:
            return explicit
        source_upper = (source or "").strip().upper()
        if source_upper in {"SWIGGY", "ECOMMERCE_SWIGGY"}:
            return GST_ORDER_SOURCE_ECOMMERCE_SWIGGY
        if source_upper in {"ZOMATO", "ECOMMERCE_ZOMATO"}:
            return GST_ORDER_SOURCE_ECOMMERCE_ZOMATO
        if (fulfillment_type or "").strip().upper() == "DINE_IN":
            return GST_ORDER_SOURCE_COUNTER_DINE_IN
        if (channel or "").strip().lower() == "counter":
            return GST_ORDER_SOURCE_COUNTER_TAKEAWAY
        if (fulfillment_type or "").strip().upper() == "PICKUP":
            return GST_ORDER_SOURCE_DIRECT_WEB_PICKUP
        return GST_ORDER_SOURCE_DIRECT_WEB_DELIVERY

    def gst_liability_party_for_source(self, gst_order_source) -> str:
        source = self.normalize_gst_order_source(gst_order_source)
        if source in GST_ECOMMERCE_ORDER_SOURCES:
            return GST_LIABILITY_ECOMMERCE_OPERATOR
        return GST_LIABILITY_BAKERY

    def gst_return_bucket_for_source(self, gst_order_source) -> str:
        source = self.normalize_gst_order_source(gst_order_source)
        if source in GST_ECOMMERCE_ORDER_SOURCES:
            return GST_RETURN_ECOMMERCE_9_5
        return GST_RETURN_OUTWARD_SUPPLIES

    def ecommerce_operator_for_source(self, gst_order_source):
        return GST_ECOMMERCE_OPERATOR_BY_SOURCE.get(
            self.normalize_gst_order_source(gst_order_source)
        )

    def ecommerce_tcs_amount(self, taxable_amount, gst_order_source) -> Decimal:
        if self.gst_liability_party_for_source(gst_order_source) != GST_LIABILITY_ECOMMERCE_OPERATOR:
            return Decimal("0.00")
        rate = Decimal(str(current_app.config.get("GST_ECOMMERCE_TCS_RATE", 1)))
        return (
            Decimal(str(taxable_amount or 0)) * rate / Decimal("100")
        ).quantize(Decimal("0.01"))

    def sales_gst_context(
        self,
        subtotal,
        *,
        discount=Decimal("0"),
        loyalty_discount=Decimal("0"),
        rate_percent=None,
        gst_order_source=None,
        channel="online",
        source=None,
        fulfillment_type="DELIVERY",
    ) -> Dict[str, Any]:
        gst = self.calculate_sales_gst(
            subtotal,
            discount=discount,
            loyalty_discount=loyalty_discount,
            rate_percent=rate_percent,
        )
        order_source = self.normalize_gst_order_source(
            gst_order_source,
            channel=channel,
            source=source,
            fulfillment_type=fulfillment_type,
        )
        liability_party = self.gst_liability_party_for_source(order_source)
        invoice_note = ""
        if liability_party == GST_LIABILITY_ECOMMERCE_OPERATOR:
            invoice_note = (
                "Tax to be deposited by E-commerce Operator under Section 9(5) "
                "of the CGST Act."
            )
        return {
            **gst,
            "gst_supply_type": GST_SUPPLY_RESTAURANT_SERVICE,
            "gst_order_source": order_source,
            "gst_order_source_label": GST_ORDER_SOURCE_LABELS.get(order_source, order_source),
            "gst_liability_party": liability_party,
            "gst_return_bucket": self.gst_return_bucket_for_source(order_source),
            "gst_invoice_note": invoice_note,
            "ecommerce_operator": self.ecommerce_operator_for_source(order_source),
            "ecommerce_tcs_amount": self.ecommerce_tcs_amount(
                gst["taxable_amount"],
                order_source,
            ),
        }

    def extract_gst_from_inclusive(
        self, inclusive_amount: Decimal, rate_percent: Decimal
    ) -> Decimal:
        """Extract GST embedded in a tax-inclusive legacy amount."""
        inclusive = Decimal(str(inclusive_amount or 0))
        rate = Decimal(str(rate_percent or 0))
        if inclusive <= 0 or rate <= 0:
            return Decimal("0")
        base = inclusive / (Decimal("1") + rate / Decimal("100"))
        return (inclusive - base).quantize(Decimal("0.01"))

    def compute_order_gst_amount(self, order: Order) -> Decimal:
        stored = Decimal(str(order.gst_amount or 0))
        if stored > 0:
            return stored.quantize(Decimal("0.01"))
        breakdown = InvoiceService(storage_service=None).calculate_gst_breakdown(order)
        return Decimal(str(breakdown["gst_amount"])).quantize(Decimal("0.01"))

    def order_gst_taxable_amount(self, order: Order) -> Decimal:
        stored = Decimal(str(getattr(order, "gst_taxable_amount", 0) or 0))
        if stored > 0:
            return stored.quantize(Decimal("0.01"))
        return self.taxable_sales_amount(
            order.subtotal,
            order.discount,
            getattr(order, "loyalty_discount", 0),
        )

    def order_gst_split(self, order: Order) -> Tuple[Decimal, Decimal]:
        cgst = Decimal(str(getattr(order, "cgst_amount", 0) or 0))
        sgst = Decimal(str(getattr(order, "sgst_amount", 0) or 0))
        if cgst > 0 or sgst > 0:
            return cgst.quantize(Decimal("0.01")), sgst.quantize(Decimal("0.01"))
        gst_amount = self.compute_order_gst_amount(order)
        cgst = (gst_amount / Decimal("2")).quantize(Decimal("0.01"))
        sgst = (gst_amount - cgst).quantize(Decimal("0.01"))
        return cgst, sgst

    def order_gst_liability_party(self, order: Order) -> str:
        stored = (getattr(order, "gst_liability_party", "") or "").strip().upper()
        if stored:
            return stored
        return self.gst_liability_party_for_source(
            getattr(order, "gst_order_source", None)
        )

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
        return branch_id, store.get("name") or current_app.config.get(
            "BAKERY_NAME", "Main Store"
        )

    def record_sale_from_order(
        self, order: Order, actor_id: Optional[int] = None
    ) -> Optional[FinancialTransaction]:
        if order is None:
            return None
        idempotency_key = f"sale-order-{order.id}"
        existing = FinancialTransaction.query.filter_by(
            idempotency_key=idempotency_key
        ).first()
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
        realized_amount = (
            Decimal(str(order.total or 0))
            + Decimal(str(getattr(order, "gift_card_redemption_amount", 0) or 0))
        ).quantize(Decimal("0.01"))
        txn = FinancialTransaction(
            transaction_type="income",
            category_id=category.id,
            amount=realized_amount,
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

    def record_refund_from_order(
        self,
        order: Order,
        *,
        amount: Optional[Decimal] = None,
        reason: str = "",
        actor_id: Optional[int] = None,
    ) -> Optional[FinancialTransaction]:
        if order is None:
            return None
        idempotency_key = f"refund-order-{order.id}"
        existing = FinancialTransaction.query.filter_by(
            idempotency_key=idempotency_key
        ).first()
        if existing:
            return existing

        category = self.get_category("refund")
        if category is None:
            self.ensure_default_categories()
            category = self.get_category("refund")
        if category is None:
            category = self.get_category("other_expense")
        if category is None:
            return None

        refund_amount = Decimal(str(amount if amount is not None else order.total or 0))
        branch_id, store_location = self._branch_context(order.branch_id)
        gst_amount = self.compute_order_gst_amount(order)
        txn = FinancialTransaction(
            transaction_type="expense",
            category_id=category.id,
            amount=refund_amount,
            tax_amount=gst_amount,
            description=f"Refund for order #{order.order_number}: {(reason or '').strip()}",
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

            action = (
                "financial_transaction_created"
                if created
                else "financial_transaction_updated"
            )
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
        payment_method: str = "",
        created_by: Optional[int] = None,
        vendor_id: Optional[int] = None,
        reference_purchase_order_id: Optional[int] = None,
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
            tds_withheld=(
                Decimal(str(tds_withheld)) if tds_withheld is not None else None
            ),
            payment_method=(payment_method or "").strip().upper() or None,
            created_by=created_by,
            vendor_id=vendor_id,
            reference_purchase_order_id=reference_purchase_order_id,
        )
        db.session.add(txn)
        self._audit_transaction(txn, created_by, created=True)
        return txn

    def vendor_financial_year_base_spend(self, vendor_id, as_of=None) -> Decimal:
        if not vendor_id:
            return Decimal("0.00")
        as_of_dt = as_of or utcnow()
        if isinstance(as_of_dt, date) and not isinstance(as_of_dt, datetime):
            as_of_dt = datetime.combine(as_of_dt, time.min)
        fy_start, fy_end = financial_year_bounds(as_of_dt)
        period_start = datetime.combine(fy_start, time.min)
        period_end = datetime.combine(fy_end + timedelta(days=1), time.min)
        txns = (
            FinancialTransaction.query.filter(
                FinancialTransaction.transaction_type == "expense",
                FinancialTransaction.vendor_id == vendor_id,
                FinancialTransaction.created_at >= period_start,
                FinancialTransaction.created_at < period_end,
            )
            .order_by(FinancialTransaction.created_at.asc())
            .all()
        )
        total = Decimal("0")
        for txn in txns:
            total += Decimal(str(txn.amount or 0))
        return total.quantize(MONEY_QUANT)

    def tds_deposit_due_date(self, deducted_at=None) -> date:
        deducted_at = deducted_at or utcnow()
        if isinstance(deducted_at, date) and not isinstance(deducted_at, datetime):
            deducted_date = deducted_at
        else:
            deducted_date = deducted_at.date()
        if deducted_date.month == 3:
            return date(deducted_date.year, 4, 30)
        if deducted_date.month == 12:
            return date(deducted_date.year + 1, 1, 7)
        return date(deducted_date.year, deducted_date.month + 1, 7)

    def purchase_order_tds_preview(
        self,
        purchase_order,
        *,
        subtotal: Optional[Decimal] = None,
        as_of=None,
    ) -> Dict[str, Any]:
        if purchase_order is None:
            return self.calculate_vendor_tds(None, Decimal("0"), as_of=as_of)
        base_amount = subtotal if subtotal is not None else purchase_order.subtotal
        return self.calculate_vendor_tds(
            purchase_order.vendor,
            base_amount,
            as_of=as_of,
        )

    def calculate_vendor_tds(
        self,
        vendor,
        invoice_base_amount,
        *,
        as_of=None,
    ) -> Dict[str, Any]:
        deducted_at = as_of or utcnow()
        base_amount = _money(invoice_base_amount)
        zero_result = {
            "applicable": False,
            "section": "",
            "rate_percent": Decimal("0"),
            "base_amount": base_amount,
            "tds_amount": Decimal("0.00"),
            "annual_spend_before": Decimal("0.00"),
            "projected_annual_spend": base_amount,
            "deposit_due_date": None,
            "reason": "",
            "pan_missing": False,
        }
        if vendor is None:
            return {**zero_result, "reason": "Vendor is missing."}
        if base_amount <= 0:
            return {**zero_result, "reason": "Invoice base amount is zero."}

        payment_type = vendor.tds_payment_type or TDS_PAYMENT_TYPE_NONE
        config = TDS_PAYMENT_TYPE_CONFIG.get(
            payment_type, TDS_PAYMENT_TYPE_CONFIG[TDS_PAYMENT_TYPE_NONE]
        )
        if not vendor.tds_enabled or payment_type == TDS_PAYMENT_TYPE_NONE:
            return {**zero_result, "reason": "TDS disabled for this vendor."}

        annual_spend_before = self.vendor_financial_year_base_spend(
            vendor.id, as_of=deducted_at
        )
        projected_annual_spend = (annual_spend_before + base_amount).quantize(
            MONEY_QUANT
        )
        rate_percent = (
            Decimal(str(vendor.tds_rate_percent))
            if vendor.tds_rate_percent is not None
            else config["rate"]
        )
        annual_threshold = (
            Decimal(str(vendor.tds_threshold_amount))
            if vendor.tds_threshold_amount is not None
            else config["annual_threshold"]
        )
        single_threshold = config["single_threshold"]
        annual_crossed = annual_threshold <= 0 or projected_annual_spend > annual_threshold
        single_crossed = (
            single_threshold is not None and base_amount > Decimal(str(single_threshold))
        )
        if not (annual_crossed or single_crossed):
            return {
                **zero_result,
                "annual_spend_before": annual_spend_before,
                "projected_annual_spend": projected_annual_spend,
                "section": config["section"],
                "rate_percent": rate_percent,
                "reason": "Vendor threshold has not been crossed for this financial year.",
            }

        pan_missing = not vendor.pan_on_file
        applied_rate = TDS_NO_PAN_RATE if pan_missing else rate_percent
        tds_amount = (base_amount * applied_rate / Decimal("100")).quantize(
            MONEY_QUANT
        )
        threshold_reason = (
            "single-invoice threshold crossed"
            if single_crossed
            else "annual vendor threshold crossed"
        )
        if annual_threshold <= 0:
            threshold_reason = "admin configured TDS from first invoice"
        reason = f"{config['section']} {threshold_reason}"
        if pan_missing:
            reason = f"{reason}; PAN missing, so 20% rate applied"
        return {
            "applicable": tds_amount > 0,
            "section": config["section"],
            "rate_percent": applied_rate,
            "base_amount": base_amount,
            "tds_amount": tds_amount,
            "annual_spend_before": annual_spend_before,
            "projected_annual_spend": projected_annual_spend,
            "deposit_due_date": self.tds_deposit_due_date(deducted_at),
            "reason": reason,
            "pan_missing": pan_missing,
        }

    def log_restock_expense(
        self,
        movement: StockMovement,
        *,
        amount: Decimal,
        tax_amount: Optional[Decimal] = None,
        counterparty: str = "",
        vendor_id: Optional[int] = None,
        reference_purchase_order_id: Optional[int] = None,
        created_by: Optional[int] = None,
    ) -> FinancialTransaction:
        idempotency_key = f"restock-movement-{movement.id}"
        existing = FinancialTransaction.query.filter_by(
            idempotency_key=idempotency_key
        ).first()
        if existing:
            return existing

        category = self.get_category("raw_material_purchase")
        if category is None:
            self.ensure_default_categories()
            category = self.get_category("raw_material_purchase")

        material = movement.raw_material
        branch_id, store_location = self._branch_context(
            material.branch_id if material else None
        )
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
            counterparty=(counterparty or (material.supplier if material else ""))
            or None,
            reference_stock_movement_id=movement.id,
            reference_purchase_order_id=reference_purchase_order_id,
            vendor_id=vendor_id,
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

    def resolve_period_range(
        self,
        period: str = "month",
        start_date=None,
        end_date=None,
    ) -> Dict[str, Any]:
        period = PERIOD_ALIASES.get(
            (period or "month").strip().lower(), (period or "month").strip().lower()
        )
        if period not in FINANCE_PERIODS:
            period = "month"

        if period == "custom":
            if not start_date or not end_date:
                today = utcnow().date()
                start_date = today.replace(day=1).isoformat()
                end_date = today.isoformat()
            start, end = period_bounds(
                "custom", start_date=start_date, end_date=end_date
            )
            label = "Custom Range"
        elif period == "financial_year":
            fy_start, fy_end = financial_year_bounds()
            start, end = period_bounds("custom", start_date=fy_start, end_date=fy_end)
            label = f"FY {fy_start.year}-{str(fy_end.year)[-2:]}"
        else:
            analytics_period = "today" if period == "day" else period
            start, end = period_bounds(analytics_period)
            label = PERIOD_LABELS.get(analytics_period, period.title())

        inclusive_end = (end - timedelta(days=1)).date()
        return {
            "period": period,
            "label": label,
            "start": start,
            "end": end,
            "start_date": start.date().isoformat(),
            "end_date": inclusive_end.isoformat(),
        }

    def _transactions_in_period(
        self, start: datetime, end: datetime, transaction_type: Optional[str] = None
    ):
        query = FinancialTransaction.query.filter(
            FinancialTransaction.created_at >= start,
            FinancialTransaction.created_at < end,
        )
        if transaction_type:
            query = query.filter_by(transaction_type=transaction_type)
        return query.all()

    def _sales_category(self):
        category = self.get_category("sales")
        if category is None:
            self.ensure_default_categories()
            category = self.get_category("sales")
        return category

    def _sales_transactions_for_order_period(self, start: datetime, end: datetime):
        category = self._sales_category()
        if category is None:
            return []
        return (
            FinancialTransaction.query.join(
                Order,
                FinancialTransaction.reference_order_id == Order.id,
            )
            .filter(
                FinancialTransaction.transaction_type == "income",
                FinancialTransaction.category_id == category.id,
                *_revenue_order_filters(start, end),
            )
            .all()
        )

    def _manual_income_transactions(self, start: datetime, end: datetime):
        category = self._sales_category()
        query = FinancialTransaction.query.filter(
            FinancialTransaction.transaction_type == "income",
            FinancialTransaction.created_at >= start,
            FinancialTransaction.created_at < end,
        )
        if category:
            query = query.filter(
                (FinancialTransaction.category_id != category.id)
                | (FinancialTransaction.reference_order_id.is_(None))
            )
        return query.all()

    def sales_revenue(self, start: datetime, end: datetime) -> Decimal:
        return Decimal(
            str(
                total_revenue(
                    "custom",
                    start_date=start.date(),
                    end_date=(end - timedelta(days=1)).date(),
                )
            )
        ).quantize(Decimal("0.01"))

    def missing_sale_transaction_orders(
        self, start: Optional[datetime] = None, end: Optional[datetime] = None
    ):
        query = (
            Order.query.outerjoin(
                FinancialTransaction,
                FinancialTransaction.reference_order_id == Order.id,
            )
            .filter(
                Order.status.in_(REVENUE_ORDER_STATUSES),
                Order.payment_status.in_(REVENUE_PAYMENT_STATUSES),
                FinancialTransaction.id.is_(None),
            )
            .order_by(Order.placed_at.asc(), Order.id.asc())
        )
        if start is not None:
            query = query.filter(Order.placed_at >= start)
        if end is not None:
            query = query.filter(Order.placed_at < end)
        return query.all()

    def backfill_missing_sale_transactions(
        self,
        *,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        commit: bool = False,
        actor_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        orders = self.missing_sale_transaction_orders(start=start, end=end)
        created = []
        self.ensure_default_categories()
        for order in orders:
            txn = self.record_sale_from_order(order, actor_id=actor_id)
            if txn:
                created.append(order.id)
        if commit:
            db.session.commit()
        else:
            db.session.rollback()
        return {"checked": len(orders), "created": len(created), "order_ids": created}

    def revenue_consistency_check(
        self, start_date=None, end_date=None
    ) -> Dict[str, Any]:
        start, end = period_bounds("custom", start_date=start_date, end_date=end_date)
        order_revenue = self.sales_revenue(start, end)
        ledger_revenue = self._sum_amounts(
            self._sales_transactions_for_order_period(start, end)
        )
        difference = (order_revenue - ledger_revenue).quantize(Decimal("0.01"))
        missing_orders = self.missing_sale_transaction_orders(start, end)
        return {
            "start": start,
            "end": end,
            "order_revenue": order_revenue,
            "ledger_revenue": ledger_revenue,
            "difference": difference,
            "matches": difference == Decimal("0.00") and not missing_orders,
            "missing_count": len(missing_orders),
            "missing_orders": missing_orders[:25],
        }

    def _sum_amounts(self, transactions: List[FinancialTransaction]) -> Decimal:
        total = Decimal("0")
        for txn in transactions:
            total += Decimal(str(txn.amount or 0))
        return total.quantize(Decimal("0.01"))

    def _sum_tax(self, transactions: List[FinancialTransaction]) -> Decimal:
        total = Decimal("0")
        for txn in transactions:
            if txn.vendor_id and txn.vendor and not txn.vendor.gstin:
                continue
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
        sales_revenue = self.sales_revenue(start, end)
        sales_txns = self._sales_transactions_for_order_period(start, end)
        manual_income_txns = self._manual_income_transactions(start, end)
        expense_txns = self._transactions_in_period(start, end, "expense")
        other_income = self._sum_amounts(manual_income_txns)
        income = (sales_revenue + other_income).quantize(Decimal("0.01"))
        expenses = self._sum_amounts(expense_txns)
        net = (income - expenses).quantize(Decimal("0.01"))
        return {
            "start": start,
            "end": end,
            "sales_revenue": sales_revenue,
            "other_income": other_income,
            "income": income,
            "expenses": expenses,
            "net_profit": net,
            "sales_transactions": sales_txns,
            "income_transactions": sales_txns + manual_income_txns,
            "manual_income_transactions": manual_income_txns,
            "expense_transactions": expense_txns,
        }

    def category_breakdown(
        self, start_date=None, end_date=None
    ) -> Dict[str, List[Dict[str, Any]]]:
        start, end = period_bounds("custom", start_date=start_date, end_date=end_date)
        sales_category = self._sales_category()
        income_rows: Dict[str, Dict[str, Any]] = {}
        if sales_category:
            sales_revenue = self.sales_revenue(start, end)
            income_rows[sales_category.label] = {
                "category": sales_category.label,
                "transaction_type": "income",
                "amount": sales_revenue,
            }
        for txn in self._manual_income_transactions(start, end):
            label = txn.category.label if txn.category else "Other Income"
            bucket = income_rows.setdefault(
                label,
                {
                    "category": label,
                    "transaction_type": "income",
                    "amount": Decimal("0"),
                },
            )
            bucket["amount"] += Decimal(str(txn.amount or 0))

        expense_rows: Dict[str, Dict[str, Any]] = {}
        for txn in self._transactions_in_period(start, end, "expense"):
            label = txn.category.label if txn.category else "Other Expense"
            bucket = expense_rows.setdefault(
                label,
                {
                    "category": label,
                    "transaction_type": "expense",
                    "amount": Decimal("0"),
                },
            )
            bucket["amount"] += Decimal(str(txn.amount or 0))

        def normalize(rows):
            return sorted(
                [
                    {
                        **row,
                        "amount": Decimal(str(row["amount"])).quantize(Decimal("0.01")),
                    }
                    for row in rows.values()
                ],
                key=lambda item: item["amount"],
                reverse=True,
            )

        return {"income": normalize(income_rows), "expenses": normalize(expense_rows)}

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
            unit_cogs[recipe.product_id] = unit_cogs.get(
                recipe.product_id, Decimal("0")
            ) + (
                Decimal(str(recipe.quantity_required or 0))
                * Decimal(str(material.cost_per_unit or 0))
            )

        ledger = []
        for row in sales_rows:
            product_id = row.product_id
            units = Decimal(str(row.units_sold or 0))
            revenue = Decimal(str(row.revenue or 0))
            cogs = (unit_cogs.get(product_id, Decimal("0")) * units).quantize(
                Decimal("0.01")
            )
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

        sales_rows = (
            db.session.query(
                Order.branch_id,
                func.coalesce(Branch.name, Order.branch_id).label("store"),
                func.coalesce(
                    func.sum(
                        Order.total
                        + func.coalesce(Order.gift_card_redemption_amount, 0)
                    ),
                    0,
                ).label("income"),
            )
            .outerjoin(Branch, Branch.id == Order.branch_id)
            .filter(*_revenue_order_filters(start, end))
            .group_by(Order.branch_id, Branch.name)
            .all()
        )
        default_store = self._branch_context(None)[1]
        for row in sales_rows:
            key = str(row.store or default_store or "Unassigned")
            bucket = by_store.setdefault(
                key,
                {
                    "store": key,
                    "income": Decimal("0"),
                    "expenses": Decimal("0"),
                    "branch_id": row.branch_id,
                },
            )
            bucket["income"] += Decimal(str(row.income or 0))

        for txn in txns:
            if txn.transaction_type == "income" and txn.reference_order_id:
                continue
            key = txn.store_location or "Unassigned"
            bucket = by_store.setdefault(
                key,
                {
                    "store": key,
                    "income": Decimal("0"),
                    "expenses": Decimal("0"),
                    "branch_id": txn.branch_id,
                },
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
                    "net": (bucket["income"] - bucket["expenses"]).quantize(
                        Decimal("0.01")
                    ),
                }
            )
        return sorted(rows, key=lambda item: item["store"])

    def gst_summary(self, start_date=None, end_date=None) -> Dict[str, Any]:
        start, end = period_bounds("custom", start_date=start_date, end_date=end_date)
        expense_txns = self._transactions_in_period(start, end, "expense")
        sales_report = self.gst_sales_channel_report(start_date=start_date, end_date=end_date)
        gross_output_gst = sales_report["total_gst_shown"]
        gst_collected = sales_report["bakery_payable_gst"]
        input_gst_recorded = self._sum_tax(expense_txns)
        no_itc = bool(current_app.config.get("GST_RESTAURANT_SERVICE_NO_ITC", True))
        gst_paid = Decimal("0.00") if no_itc else input_gst_recorded
        non_creditable_input_gst = input_gst_recorded if no_itc else Decimal("0.00")
        net_liability = (gst_collected - gst_paid).quantize(Decimal("0.01"))
        return {
            "start": start,
            "end": end,
            "gross_output_gst": gross_output_gst,
            "gst_collected": gst_collected,
            "ecommerce_operator_gst": sales_report["ecommerce_operator_gst"],
            "input_gst_recorded": input_gst_recorded,
            "gst_paid": gst_paid,
            "non_creditable_input_gst": non_creditable_input_gst,
            "net_gst_liability": net_liability,
            "restaurant_no_itc": no_itc,
            "ecommerce_tcs": sales_report["ecommerce_tcs"],
            "regular_outward_taxable": sales_report["regular_outward_taxable"],
            "ecommerce_taxable": sales_report["ecommerce_taxable"],
            "rows": sales_report["rows"],
            "gstr1_mapping": sales_report["gstr1_mapping"],
        }

    def gst_sales_channel_report(self, start_date=None, end_date=None) -> Dict[str, Any]:
        start, end = period_bounds("custom", start_date=start_date, end_date=end_date)
        orders = (
            Order.query.filter(
                Order.status.in_(REVENUE_ORDER_STATUSES),
                Order.payment_status.in_(REVENUE_PAYMENT_STATUSES),
                Order.placed_at >= start,
                Order.placed_at < end,
            )
            .order_by(Order.placed_at.asc(), Order.id.asc())
            .all()
        )
        rows = []
        regular_taxable = Decimal("0.00")
        regular_gst = Decimal("0.00")
        ecommerce_taxable = Decimal("0.00")
        ecommerce_gst = Decimal("0.00")
        ecommerce_tcs = Decimal("0.00")
        total_gst = Decimal("0.00")
        for order in orders:
            taxable = self.order_gst_taxable_amount(order)
            cgst, sgst = self.order_gst_split(order)
            gst_amount = (cgst + sgst).quantize(Decimal("0.01"))
            liability_party = self.order_gst_liability_party(order)
            order_source = self.normalize_gst_order_source(
                getattr(order, "gst_order_source", None),
                channel=order.channel,
                source=order.source,
                fulfillment_type=order.fulfillment_type,
            )
            return_bucket = (
                getattr(order, "gst_return_bucket", None)
                or self.gst_return_bucket_for_source(order_source)
            )
            tcs_amount = Decimal(
                str(getattr(order, "ecommerce_tcs_amount", 0) or 0)
            ).quantize(Decimal("0.01"))
            if liability_party == GST_LIABILITY_ECOMMERCE_OPERATOR:
                ecommerce_taxable += taxable
                ecommerce_gst += gst_amount
                ecommerce_tcs += tcs_amount
                liability_flag = "Paid by Aggregator"
            else:
                regular_taxable += taxable
                regular_gst += gst_amount
                liability_flag = "Payable by Bakery"
            total_gst += gst_amount
            rows.append(
                {
                    "order_date": order.placed_at.date() if order.placed_at else None,
                    "invoice_number": order.invoice_number or order.order_number,
                    "order_number": order.order_number,
                    "order_source": order_source,
                    "order_source_label": GST_ORDER_SOURCE_LABELS.get(
                        order_source,
                        order_source,
                    ),
                    "base_taxable_value": taxable.quantize(Decimal("0.01")),
                    "cgst_amount": cgst,
                    "sgst_amount": sgst,
                    "gst_amount": gst_amount,
                    "tax_liability_flag": liability_flag,
                    "gst_return_bucket": return_bucket,
                    "ecommerce_operator": getattr(order, "ecommerce_operator", None)
                    or self.ecommerce_operator_for_source(order_source)
                    or "",
                    "ecommerce_tcs_amount": tcs_amount,
                }
            )
        return {
            "start": start,
            "end": end,
            "rows": rows,
            "regular_outward_taxable": regular_taxable.quantize(Decimal("0.01")),
            "bakery_payable_gst": regular_gst.quantize(Decimal("0.01")),
            "ecommerce_taxable": ecommerce_taxable.quantize(Decimal("0.01")),
            "ecommerce_operator_gst": ecommerce_gst.quantize(Decimal("0.01")),
            "ecommerce_tcs": ecommerce_tcs.quantize(Decimal("0.01")),
            "total_gst_shown": total_gst.quantize(Decimal("0.01")),
            "gstr1_mapping": {
                "regular_outward_supplies": {
                    "table": "Standard outward supplies",
                    "taxable_value": regular_taxable.quantize(Decimal("0.01")),
                    "gst": regular_gst.quantize(Decimal("0.01")),
                },
                "ecommerce_operator_9_5": {
                    "table": "GSTR-1 Table 14 / Section 9(5)",
                    "taxable_value": ecommerce_taxable.quantize(Decimal("0.01")),
                    "gst": ecommerce_gst.quantize(Decimal("0.01")),
                },
            },
        }

    def vendor_spend_report(
        self, start_date=None, end_date=None
    ) -> List[Dict[str, Any]]:
        start, end = period_bounds("custom", start_date=start_date, end_date=end_date)
        txns = (
            FinancialTransaction.query.filter(
                FinancialTransaction.transaction_type == "expense",
                FinancialTransaction.vendor_id.isnot(None),
                FinancialTransaction.created_at >= start,
                FinancialTransaction.created_at < end,
            )
            .order_by(FinancialTransaction.created_at.desc())
            .all()
        )
        rows: Dict[int, Dict[str, Any]] = {}
        no_itc = bool(current_app.config.get("GST_RESTAURANT_SERVICE_NO_ITC", True))
        for txn in txns:
            vendor = txn.vendor
            vendor_id = txn.vendor_id
            name = vendor.name if vendor else txn.counterparty or "Unknown vendor"
            row = rows.setdefault(
                vendor_id,
                {
                    "vendor_id": vendor_id,
                    "vendor_name": name,
                    "total_spend": Decimal("0"),
                    "gst_paid": Decimal("0"),
                    "tds_withheld": Decimal("0"),
                    "transaction_count": 0,
                    "input_tax_credit_eligible": bool(vendor and vendor.gstin and not no_itc),
                    "input_tax_credit_blocked": no_itc,
                    "last_purchase_at": txn.created_at,
                },
            )
            row["total_spend"] += Decimal(str(txn.amount or 0))
            if txn.tax_amount is not None:
                row["gst_paid"] += Decimal(str(txn.tax_amount))
            if txn.tds_withheld is not None:
                row["tds_withheld"] += Decimal(str(txn.tds_withheld or 0))
            row["transaction_count"] += 1
            if txn.created_at and txn.created_at > row["last_purchase_at"]:
                row["last_purchase_at"] = txn.created_at

        return sorted(
            [
                {
                    **row,
                    "total_spend": row["total_spend"].quantize(Decimal("0.01")),
                    "gst_paid": row["gst_paid"].quantize(Decimal("0.01")),
                    "tds_withheld": row["tds_withheld"].quantize(Decimal("0.01")),
                }
                for row in rows.values()
            ],
            key=lambda item: item["total_spend"],
            reverse=True,
        )

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
                "section": (
                    txn.purchase_order.tds_section
                    if txn.purchase_order and txn.purchase_order.tds_section
                    else (txn.vendor.tds_section if txn.vendor else "")
                ),
                "deposit_due_date": (
                    txn.purchase_order.tds_deposit_due_date
                    if txn.purchase_order
                    else self.tds_deposit_due_date(txn.created_at)
                ),
                "deposit_status": (
                    "Deposited"
                    if txn.purchase_order and txn.purchase_order.tds_deposited_at
                    else "Pending deposit"
                ),
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
                "No expense transactions with TDS were found for this period."
                if not vendor_rows
                else ""
            ),
        }

    def finance_health_for_current_year(self) -> Dict[str, Any]:
        start, inclusive_end = financial_year_bounds()
        pnl = self.profit_and_loss(start_date=start, end_date=inclusive_end)
        gst = self.gst_summary(start_date=start, end_date=inclusive_end)
        categories = self.category_breakdown(start_date=start, end_date=inclusive_end)
        return {
            "label": f"FY {start.year}-{str(inclusive_end.year)[-2:]}",
            "start_date": start.isoformat(),
            "end_date": inclusive_end.isoformat(),
            "net_income": pnl["net_profit"],
            "total_income": pnl["income"],
            "total_expenses": pnl["expenses"],
            "tax_collected": gst["gst_collected"],
            "tax_paid": gst["gst_paid"],
            "net_tax_liability": gst["net_gst_liability"],
            "expense_categories": categories["expenses"],
        }

    def dashboard_payload(
        self, period="month", start_date=None, end_date=None
    ) -> Dict[str, Any]:
        selected = self.resolve_period_range(
            period, start_date=start_date, end_date=end_date
        )
        start_date = selected["start_date"]
        end_date = selected["end_date"]

        period_cards = []
        for key, label in [
            ("day", "Today"),
            ("week", "This Week"),
            ("month", "This Month"),
            ("year", "This Year"),
        ]:
            bounds = self.resolve_period_range(key)
            pnl = self.profit_and_loss(
                start_date=bounds["start_date"],
                end_date=bounds["end_date"],
            )
            period_cards.append(
                {
                    "key": key,
                    "label": label,
                    "revenue": pnl["sales_revenue"],
                    "expenses": pnl["expenses"],
                    "net_profit": pnl["net_profit"],
                }
            )

        analytics_period = (
            "custom"
            if selected["period"] in {"custom", "financial_year"}
            else ("today" if selected["period"] == "day" else selected["period"])
        )
        analytics = analytics_payload(
            analytics_period,
            start_date=start_date,
            end_date=end_date,
        )
        pnl = self.profit_and_loss(start_date=start_date, end_date=end_date)
        gst = self.gst_summary(start_date=start_date, end_date=end_date)
        tds = self.tds_summary(start_date=start_date, end_date=end_date)
        consistency = self.revenue_consistency_check(
            start_date=start_date, end_date=end_date
        )
        return {
            "selected_period": selected,
            "period_cards": period_cards,
            "pnl": pnl,
            "sales": analytics,
            "category_breakdown": self.category_breakdown(
                start_date=start_date, end_date=end_date
            ),
            "product_ledger": self.product_ledger(
                start_date=start_date, end_date=end_date
            ),
            "store_ledger": self.store_ledger(start_date=start_date, end_date=end_date),
            "vendor_spend": self.vendor_spend_report(
                start_date=start_date, end_date=end_date
            ),
            "gst": gst,
            "tds": tds,
            "itr_health": self.finance_health_for_current_year(),
            "consistency": consistency,
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
        record.admin_adjustment_notes = (
            admin_notes or ""
        ).strip() or record.admin_adjustment_notes
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
        current_app.logger.exception(
            "finance_sale_record_failed order_id=%s", payment.order_id
        )
        return None
