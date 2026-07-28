from decimal import Decimal

from clock import utcnow
from models import FinancialCategory, FinancialTransaction, db
from services.analytics_service import top_selling_product, total_revenue, units_sold
from services.finance_service import FinanceService


def test_sales_analytics_and_finance_pnl_share_order_revenue_source(
    db_session,
    order_factory,
):
    service = FinanceService()
    service.ensure_default_categories()
    now = utcnow()
    order = order_factory(
        status="DELIVERED",
        payment_status="PAID",
        quantity=3,
        total=Decimal("375"),
    )
    order.placed_at = now
    order.updated_at = now
    sale_txn = service.record_sale_from_order(order)

    expense_category = FinancialCategory.query.filter_by(code="utilities").first()
    assert expense_category is not None
    expense = service.create_manual_transaction(
        transaction_type="expense",
        category_id=expense_category.id,
        amount=Decimal("75"),
        tax_amount=Decimal("5"),
        description="Test utilities",
        counterparty="Test Vendor",
    )
    expense.created_at = now
    db_session.commit()

    start = now.date()
    end = now.date()
    assert total_revenue("custom", start_date=start, end_date=end) == Decimal("375.00")

    pnl = service.profit_and_loss(start_date=start, end_date=end)
    assert pnl["sales_revenue"] == Decimal("375.00")
    assert pnl["income"] == Decimal("375.00")
    assert pnl["expenses"] == Decimal("75.00")
    assert pnl["net_profit"] == Decimal("300.00")

    consistency = service.revenue_consistency_check(start_date=start, end_date=end)
    assert consistency["matches"] is True
    assert consistency["difference"] == Decimal("0.00")
    assert sale_txn in pnl["sales_transactions"]


def test_sales_performance_counts_paid_delivered_units_only(
    db_session,
    order_factory,
):
    now = utcnow()
    delivered_paid = order_factory(
        status="DELIVERED",
        payment_status="PAID",
        quantity=4,
        total=Decimal("400"),
    )
    delivered_paid.placed_at = now
    pending = order_factory(
        status="DELIVERED",
        payment_status="PENDING",
        quantity=9,
        total=Decimal("900"),
    )
    pending.placed_at = now
    db_session.commit()

    start = now.date()
    end = now.date()
    rows = units_sold("custom", start_date=start, end_date=end)
    assert sum(row["units_sold"] for row in rows) == 4
    assert sum(Decimal(str(row["revenue"])) for row in rows) == Decimal("400.0")

    top = top_selling_product("custom", start_date=start, end_date=end)
    assert top["by_units"]["units_sold"] == 4
    assert top["by_revenue"]["revenue"] == 400.0


def test_finance_consistency_check_flags_missing_ledger_transaction(
    db_session,
    order_factory,
):
    now = utcnow()
    order = order_factory(
        status="DELIVERED",
        payment_status="PAID",
        total=Decimal("180"),
    )
    order.placed_at = now
    db_session.commit()

    result = FinanceService().revenue_consistency_check(
        start_date=now.date(),
        end_date=now.date(),
    )

    assert result["matches"] is False
    assert result["order_revenue"] == Decimal("180.00")
    assert result["ledger_revenue"] == Decimal("0.00")
    assert result["missing_count"] == 1
    assert result["missing_orders"][0].id == order.id
    assert (
        FinancialTransaction.query.filter_by(reference_order_id=order.id).first()
        is None
    )
