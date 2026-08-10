from datetime import date, datetime, time, timedelta
from decimal import Decimal

from dateutil.relativedelta import relativedelta
from sqlalchemy import desc, func

from clock import utcnow
from models import ConversionEvent, Order, OrderItem, Product, TableMenuScan, db


REVENUE_ORDER_STATUSES = ("DELIVERED",)
REVENUE_PAYMENT_STATUSES = ("PAID",)
PERIODS = {"today", "week", "month", "year"}
PERIOD_LABELS = {
    "today": "Today",
    "week": "This Week",
    "month": "This Month",
    "year": "This Year",
}


def _parse_date(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, time.min)
    if isinstance(value, str):
        return datetime.combine(datetime.strptime(value, "%Y-%m-%d").date(), time.min)
    raise ValueError("Expected a date, datetime, or YYYY-MM-DD string.")


def _exclusive_end(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value + timedelta(days=1), time.min)
    if isinstance(value, str):
        return datetime.combine(
            datetime.strptime(value, "%Y-%m-%d").date() + timedelta(days=1),
            time.min,
        )
    raise ValueError("Expected a date, datetime, or YYYY-MM-DD string.")


def period_bounds(period="today", start_date=None, end_date=None, now=None):
    if isinstance(period, (tuple, list)) and len(period) == 2:
        start_date, end_date = period
        period = "custom"

    if start_date is not None or end_date is not None or period == "custom":
        start = _parse_date(start_date)
        end = _exclusive_end(end_date)
        if start is None or end is None:
            raise ValueError("Custom analytics ranges require start_date and end_date.")
        if end <= start:
            raise ValueError("Analytics end_date must be after start_date.")
        return start, end

    period = (period or "today").strip().lower()
    if period not in PERIODS:
        raise ValueError(f"Unsupported analytics period: {period}")

    current = now or utcnow()
    today = current.date()
    if period == "today":
        start = datetime.combine(today, time.min)
        end = start + timedelta(days=1)
    elif period == "week":
        start = datetime.combine(today - timedelta(days=today.weekday()), time.min)
        end = start + timedelta(days=7)
    elif period == "month":
        start = datetime.combine(today.replace(day=1), time.min)
        end = start + relativedelta(months=1)
    else:
        start = datetime.combine(today.replace(month=1, day=1), time.min)
        end = start + relativedelta(years=1)
    return start, end


def _revenue_order_filters(start, end):
    return (
        Order.status.in_(REVENUE_ORDER_STATUSES),
        Order.payment_status.in_(REVENUE_PAYMENT_STATUSES),
        Order.placed_at >= start,
        Order.placed_at < end,
    )


def total_revenue(period="today", start_date=None, end_date=None):
    start, end = period_bounds(period, start_date=start_date, end_date=end_date)
    realized_total = Order.total + func.coalesce(Order.gift_card_redemption_amount, 0)
    return db.session.query(func.coalesce(func.sum(realized_total), 0)).filter(
        *_revenue_order_filters(start, end)
    ).scalar() or Decimal("0")


def _product_sales_query(start, end):
    return (
        db.session.query(
            OrderItem.product_id.label("product_id"),
            func.coalesce(Product.name, func.max(OrderItem.product_name)).label(
                "product_name"
            ),
            func.coalesce(func.sum(OrderItem.quantity), 0).label("units_sold"),
            func.coalesce(func.sum(OrderItem.subtotal), 0).label("revenue"),
        )
        .join(Order, OrderItem.order_id == Order.id)
        .outerjoin(Product, Product.id == OrderItem.product_id)
        .filter(*_revenue_order_filters(start, end))
        .group_by(OrderItem.product_id, Product.name)
    )


def _serialize_product_row(row):
    if row is None:
        return None
    return {
        "product_id": row.product_id,
        "product_name": row.product_name or "Unknown product",
        "units_sold": int(row.units_sold or 0),
        "revenue": float(row.revenue or 0),
    }


def units_sold(period="today", start_date=None, end_date=None, limit=None):
    start, end = period_bounds(period, start_date=start_date, end_date=end_date)
    query = _product_sales_query(start, end).order_by(
        desc("units_sold"), desc("revenue")
    )
    if limit:
        query = query.limit(limit)
    return [_serialize_product_row(row) for row in query.all()]


def top_selling_product(period="today", start_date=None, end_date=None):
    start, end = period_bounds(period, start_date=start_date, end_date=end_date)
    by_units = (
        _product_sales_query(start, end)
        .order_by(desc("units_sold"), desc("revenue"))
        .limit(1)
        .first()
    )
    by_revenue = (
        _product_sales_query(start, end)
        .order_by(desc("revenue"), desc("units_sold"))
        .limit(1)
        .first()
    )
    return {
        "by_units": _serialize_product_row(by_units),
        "by_revenue": _serialize_product_row(by_revenue),
    }


def _bucket_expression(granularity):
    dialect = db.session.get_bind().dialect.name
    if granularity == "hour":
        return func.extract("hour", Order.placed_at)
    if granularity == "month":
        if dialect in {"mysql", "mariadb"}:
            return func.date_format(Order.placed_at, "%Y-%m")
        return func.strftime("%Y-%m", Order.placed_at)
    if dialect in {"mysql", "mariadb"}:
        return func.date_format(Order.placed_at, "%Y-%m-%d")
    return func.strftime("%Y-%m-%d", Order.placed_at)


def _bucket_labels(start, end, granularity):
    labels = []
    cursor = start
    if granularity == "hour":
        return [f"{hour:02d}:00" for hour in range(24)]
    if granularity == "month":
        cursor = datetime.combine(start.date().replace(day=1), time.min)
        while cursor < end:
            labels.append(cursor.strftime("%Y-%m"))
            cursor += relativedelta(months=1)
        return labels
    while cursor < end:
        labels.append(cursor.strftime("%Y-%m-%d"))
        cursor += timedelta(days=1)
    return labels


def _normalize_bucket(value, granularity):
    if granularity == "hour":
        return f"{int(value):02d}:00"
    if isinstance(value, datetime):
        return value.strftime("%Y-%m" if granularity == "month" else "%Y-%m-%d")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%d")
    return str(value)


def default_granularity(period):
    period = (period or "today").strip().lower()
    if period == "today":
        return "hour"
    if period == "year":
        return "month"
    return "day"


def revenue_trend(period="month", granularity=None, start_date=None, end_date=None):
    granularity = (granularity or default_granularity(period)).strip().lower()
    if granularity not in {"hour", "day", "month"}:
        raise ValueError("granularity must be hour, day, or month.")

    start, end = period_bounds(period, start_date=start_date, end_date=end_date)
    bucket = _bucket_expression(granularity).label("bucket")
    rows = (
        db.session.query(
            bucket,
            func.coalesce(
                func.sum(
                    Order.total + func.coalesce(Order.gift_card_redemption_amount, 0)
                ),
                0,
            ).label("revenue"),
        )
        .filter(*_revenue_order_filters(start, end))
        .group_by(bucket)
        .order_by(bucket)
        .all()
    )
    revenue_by_bucket = {
        _normalize_bucket(row.bucket, granularity): float(row.revenue or 0)
        for row in rows
    }

    labels = _bucket_labels(start, end, granularity)
    return [
        {"label": label, "revenue": revenue_by_bucket.get(label, 0.0)}
        for label in labels
    ]


def analytics_payload(period="month", granularity=None, start_date=None, end_date=None):
    granularity = granularity or default_granularity(period)
    start, end = period_bounds(period, start_date=start_date, end_date=end_date)
    event_counts = dict(
        db.session.query(ConversionEvent.event_name, func.count(ConversionEvent.id))
        .filter(ConversionEvent.created_at >= start, ConversionEvent.created_at < end)
        .group_by(ConversionEvent.event_name)
        .all()
    )
    order_count = (
        Order.query.filter(Order.placed_at >= start, Order.placed_at < end).count()
    )
    delivered_paid_orders = (
        Order.query.filter(*_revenue_order_filters(start, end)).count()
    )
    qr_scan_count = (
        TableMenuScan.query.filter(
            TableMenuScan.created_at >= start,
            TableMenuScan.created_at < end,
        ).count()
    )
    dine_in_orders = (
        Order.query.filter(
            Order.placed_at >= start,
            Order.placed_at < end,
            Order.fulfillment_type == "DINE_IN",
        ).count()
    )
    return {
        "period": period,
        "period_label": PERIOD_LABELS.get(period, "Custom Range"),
        "granularity": granularity,
        "revenue": float(
            total_revenue(period, start_date=start_date, end_date=end_date)
        ),
        "trend": revenue_trend(
            period,
            granularity=granularity,
            start_date=start_date,
            end_date=end_date,
        ),
        "units_sold": units_sold(
            period, start_date=start_date, end_date=end_date, limit=10
        ),
        "top_sellers": top_selling_product(
            period,
            start_date=start_date,
            end_date=end_date,
        ),
        "conversion": {
            "page_views": int(event_counts.get("page_view", 0)),
            "product_views": int(
                event_counts.get("view_item", 0)
                + event_counts.get("product_view", 0)
            ),
            "add_to_cart": int(event_counts.get("add_to_cart", 0)),
            "checkout_starts": int(event_counts.get("begin_checkout", 0)),
            "purchases": int(event_counts.get("purchase", 0) or delivered_paid_orders),
            "purchase_conversion_rate": round(
                (delivered_paid_orders / max(int(event_counts.get("page_view", 0)), 1)) * 100,
                2,
            ),
            "cart_abandonment": max(
                int(event_counts.get("add_to_cart", 0))
                - int(event_counts.get("begin_checkout", 0)),
                0,
            ),
            "checkout_abandonment": max(
                int(event_counts.get("begin_checkout", 0)) - delivered_paid_orders,
                0,
            ),
            "orders_created": order_count,
            "qr_menu_scans": qr_scan_count,
            "dine_in_orders": dine_in_orders,
            "corporate_leads": int(event_counts.get("corporate_inquiry_submitted", 0)),
            "subscription_conversions": int(event_counts.get("subscription_started", 0)),
        },
    }
