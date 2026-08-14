from datetime import date, datetime, timedelta
from decimal import Decimal
import csv
import io
from pathlib import Path

from dateutil.relativedelta import relativedelta
from flask import (
    Blueprint,
    Response,
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)
from flask_login import current_user
from sqlalchemy import func, or_
from sqlalchemy.orm import selectinload
from werkzeug.utils import secure_filename

from bootstrap import get_container
from clock import utcnow
from models import (
    AuditDocument,
    AuditReportDownload,
    AUDIT_DOCUMENT_CATEGORIES,
    AUDIT_REQUIREMENT_CATEGORIES,
    AUDIT_REQUIREMENT_PRIORITIES,
    AUDIT_REQUIREMENT_STATUSES,
    AuditorRequirement,
    AuditorRequirementEvent,
    Branch,
    BranchInventory,
    FinancialCategory,
    FinancialTransaction,
    Order,
    OrderItem,
    Product,
    ProductVariant,
    PurchaseOrder,
    RawMaterial,
    SalaryRecord,
    StockMovement,
    User,
    Vendor,
    db,
)
from services.analytics_service import (
    REVENUE_ORDER_STATUSES,
    REVENUE_PAYMENT_STATUSES,
    period_bounds,
)
from services.finance_service import financial_year_bounds
from utils.permissions import has_role


audit_bp = Blueprint("audit", __name__)

AUDIT_REPORTS = {
    "sales-register": "Sales Register",
    "revenue-report": "Revenue Report",
    "purchase-register": "Purchase Register",
    "expense-register": "Expense Report",
    "gst-report": "GST Report",
    "profit-and-loss": "Profit and Loss",
    "inventory-valuation": "Inventory Valuation",
    "branch-financial-report": "Branch Financial Report",
    "cash-summary": "Cash Summary",
}
AUDIT_DOCUMENT_CATEGORIES = (
    "Financial Statements",
    "Sales",
    "Purchases",
    "GST",
    "Tax",
    "Bank",
    "Payroll",
    "Assets",
    "Loans",
    "Audit Reports",
    "Other",
)
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
AUDITOR_WRITE_ENDPOINTS = {
    "audit.requirements",
    "audit.request_revision",
    "audit.resolve_requirement",
}
PAGE_SIZE = 25


def money(value):
    return Decimal(str(value or 0)).quantize(Decimal("0.01"))


def current_financial_year_label(now=None):
    start, end = financial_year_bounds(now)
    return f"{start.year}-{str(end.year)[-2:]}"


def available_financial_years(now=None, count=5):
    start, _end = financial_year_bounds(now)
    return [
        f"{start.year - offset}-{str(start.year - offset + 1)[-2:]}"
        for offset in range(count)
    ]


def audit_requirement_uid():
    prefix = f"REQ-{utcnow().year}-"
    latest = (
        AuditorRequirement.query.filter(
            AuditorRequirement.requirement_uid.like(f"{prefix}%")
        )
        .order_by(AuditorRequirement.id.desc())
        .first()
    )
    next_number = 1
    if latest and latest.requirement_uid:
        try:
            next_number = int(latest.requirement_uid.rsplit("-", 1)[1]) + 1
        except (IndexError, ValueError):
            next_number = (latest.id or 0) + 1
    return f"{prefix}{next_number:04d}"


def audit_requirement_event(requirement, event_type, message=""):
    event = AuditorRequirementEvent(
        requirement=requirement,
        actor_id=current_user.id,
        event_type=event_type,
        message=(message or "").strip() or None,
    )
    db.session.add(event)
    return event


def auditor_requirement_or_404(requirement_id):
    query = AuditorRequirement.query.options(
        selectinload(AuditorRequirement.auditor),
        selectinload(AuditorRequirement.documents),
        selectinload(AuditorRequirement.events).selectinload(AuditorRequirementEvent.actor),
    ).filter_by(id=requirement_id)
    if has_role(current_user, "auditor"):
        query = query.filter(AuditorRequirement.auditor_id == current_user.id)
    requirement = query.first()
    if requirement is None:
        abort(404)
    return requirement


def financial_year_dates(label):
    if not label:
        return financial_year_bounds()
    try:
        start_year = int(str(label).split("-", 1)[0])
    except (TypeError, ValueError):
        return financial_year_bounds()
    return date(start_year, 4, 1), date(start_year + 1, 3, 31)


def is_admin_preview():
    return current_user.is_authenticated and has_role(current_user, "admin", "super_admin")


@audit_bp.before_request
def enforce_audit_access():
    if not current_user.is_authenticated:
        flash("Authentication required.", "danger")
        return redirect(url_for("auth.login", next=request.full_path.rstrip("?")))

    if has_role(current_user, "auditor"):
        if request.method not in SAFE_METHODS and request.endpoint not in AUDITOR_WRITE_ENDPOINTS:
            abort(403)
        return None

    if is_admin_preview():
        if request.method not in SAFE_METHODS:
            abort(403)
        return None

    abort(403)


@audit_bp.route("/<path:_blocked_path>", methods=["POST", "PUT", "PATCH", "DELETE"])
def reject_audit_mutation(_blocked_path):
    abort(403)


def selected_period():
    selected_fy = request.args.get("financial_year") or current_financial_year_label()
    fy_start, fy_end = financial_year_dates(selected_fy)
    start_raw = request.args.get("start_date")
    end_raw = request.args.get("end_date")
    try:
        start = date.fromisoformat(start_raw) if start_raw else fy_start
        end = date.fromisoformat(end_raw) if end_raw else fy_end
    except ValueError:
        start, end = fy_start, fy_end
    if end < start:
        start, end = fy_start, fy_end
    start_dt, end_dt = period_bounds("custom", start_date=start, end_date=end)
    return {
        "financial_year": selected_fy,
        "start_date": start,
        "end_date": end,
        "start": start_dt,
        "end": end_dt,
        "label": f"{start.strftime('%d %b %Y')} to {end.strftime('%d %b %Y')}",
    }


def previous_period(period):
    days = max(1, (period["end_date"] - period["start_date"]).days + 1)
    previous_end = period["start_date"] - timedelta(days=1)
    previous_start = previous_end - timedelta(days=days - 1)
    start_dt, end_dt = period_bounds(
        "custom",
        start_date=previous_start,
        end_date=previous_end,
    )
    return {
        "start_date": previous_start,
        "end_date": previous_end,
        "start": start_dt,
        "end": end_dt,
    }


def pct_change(current, previous):
    current = money(current)
    previous = money(previous)
    if previous == 0:
        return None
    return ((current - previous) / previous * Decimal("100")).quantize(Decimal("0.1"))


def branch_options():
    return Branch.query.order_by(Branch.name.asc()).all()


def requested_branch_id():
    return request.args.get("branch_id", type=int)


def audit_shell_context():
    period = selected_period()
    return {
        "financial_years": available_financial_years(),
        "selected_financial_year": period["financial_year"],
        "selected_period": period,
        "branches": branch_options(),
        "selected_branch_id": requested_branch_id(),
        "admin_preview": is_admin_preview() and not has_role(current_user, "auditor"),
        "last_updated_at": utcnow(),
        "read_only_mode": True,
    }


def branch_filtered_order_query(period):
    query = Order.query.options(selectinload(Order.branch), selectinload(Order.customer)).filter(
        Order.placed_at >= period["start"],
        Order.placed_at < period["end"],
    )
    branch_id = requested_branch_id()
    if branch_id:
        query = query.filter(Order.branch_id == branch_id)
    search = (request.args.get("q") or "").strip()
    if search:
        like = f"%{search}%"
        query = query.outerjoin(User, User.id == Order.user_id).filter(
            or_(
                Order.order_number.ilike(like),
                Order.invoice_number.ilike(like),
                User.name.ilike(like),
                User.email.ilike(like),
            )
        )
    status = (request.args.get("status") or "").strip().upper()
    if status:
        query = query.filter(Order.status == status)
    payment_status = (request.args.get("payment_status") or "").strip().upper()
    if payment_status:
        query = query.filter(Order.payment_status == payment_status)
    payment_method = (request.args.get("payment_method") or "").strip()
    if payment_method:
        query = query.filter(Order.payment_method == payment_method)
    return query


def revenue_order_query(period):
    return branch_filtered_order_query(period).filter(
        Order.status.in_(REVENUE_ORDER_STATUSES),
        Order.payment_status.in_(REVENUE_PAYMENT_STATUSES),
    )


def expense_query(period):
    query = FinancialTransaction.query.options(
        selectinload(FinancialTransaction.category),
        selectinload(FinancialTransaction.branch),
        selectinload(FinancialTransaction.vendor),
    ).filter(
        FinancialTransaction.transaction_type == "expense",
        FinancialTransaction.created_at >= period["start"],
        FinancialTransaction.created_at < period["end"],
    )
    branch_id = requested_branch_id()
    if branch_id:
        query = query.filter(FinancialTransaction.branch_id == branch_id)
    category_id = request.args.get("category_id", type=int)
    if category_id:
        query = query.filter(FinancialTransaction.category_id == category_id)
    vendor_id = request.args.get("vendor_id", type=int)
    if vendor_id:
        query = query.filter(FinancialTransaction.vendor_id == vendor_id)
    search = (request.args.get("q") or "").strip()
    if search:
        like = f"%{search}%"
        query = query.filter(
            or_(
                FinancialTransaction.description.ilike(like),
                FinancialTransaction.counterparty.ilike(like),
                FinancialTransaction.store_location.ilike(like),
            )
        )
    return query


def purchase_query(period):
    query = PurchaseOrder.query.options(
        selectinload(PurchaseOrder.vendor),
    ).filter(
        PurchaseOrder.order_date >= period["start_date"],
        PurchaseOrder.order_date <= period["end_date"],
    )
    vendor_id = request.args.get("vendor_id", type=int)
    if vendor_id:
        query = query.filter(PurchaseOrder.vendor_id == vendor_id)
    status = (request.args.get("status") or "").strip().lower()
    if status:
        query = query.filter(PurchaseOrder.status == status)
    search = (request.args.get("q") or "").strip()
    if search:
        like = f"%{search}%"
        query = query.join(Vendor).filter(or_(Vendor.name.ilike(like), Vendor.gstin.ilike(like)))
    return query


def sales_summary(query):
    totals = query.with_entities(
        func.coalesce(func.sum(Order.subtotal), 0),
        func.coalesce(func.sum(Order.discount), 0),
        func.coalesce(func.sum(Order.loyalty_discount), 0),
        func.coalesce(func.sum(Order.gst_taxable_amount), 0),
        func.coalesce(func.sum(Order.gst_amount), 0),
        func.coalesce(func.sum(Order.total), 0),
        func.count(Order.id),
    ).one()
    cancelled = query.filter(Order.status == "CANCELLED").with_entities(
        func.coalesce(func.sum(Order.total), 0)
    ).scalar()
    refunded = query.filter(Order.status == "REFUNDED").with_entities(
        func.coalesce(func.sum(Order.total), 0)
    ).scalar()
    discount_total = money(totals[1]) + money(totals[2])
    return {
        "gross_sales": money(totals[0]),
        "net_sales": money(totals[5]),
        "taxable_sales": money(totals[3]),
        "gst_collected": money(totals[4]),
        "discounts": discount_total,
        "refunds": money(refunded),
        "cancelled_sales": money(cancelled),
        "invoice_count": totals[6],
    }


def purchase_summary(query):
    orders = query.all()
    total = sum((po.subtotal for po in orders), Decimal("0"))
    gst = sum(
        (money(po.subtotal) * Decimal(str(po.gst_rate_percent or 0)) / Decimal("100"))
        for po in orders
    )
    open_total = sum(
        (po.subtotal for po in orders if (po.status or "").lower() not in {"received", "closed", "cancelled"}),
        Decimal("0"),
    )
    return {
        "total_purchases": money(total),
        "taxable_purchases": money(total),
        "gst_paid": money(gst),
        "input_gst": money(gst),
        "outstanding_payables": money(open_total),
        "purchase_returns": Decimal("0.00"),
        "invoice_count": len(orders),
    }


def expense_summary(query):
    rows = query.all()
    total = sum((money(row.amount) for row in rows), Decimal("0"))
    tax = sum((money(row.tax_amount) for row in rows), Decimal("0"))
    by_category = {}
    for txn in rows:
        label = txn.category.label if txn.category else "Uncategorized"
        by_category[label] = by_category.get(label, Decimal("0")) + money(txn.amount)
    return {
        "total_expenses": money(total),
        "tax_amount": money(tax),
        "categories": sorted(by_category.items(), key=lambda item: item[1], reverse=True),
        "transaction_count": len(rows),
    }


def inventory_summary():
    raw_value = db.session.query(
        func.coalesce(func.sum(RawMaterial.stock * RawMaterial.cost_per_unit), 0)
    ).scalar()
    branch_raw_rows = (
        db.session.query(
            Branch.id,
            Branch.name,
            func.coalesce(func.sum(RawMaterial.stock * RawMaterial.cost_per_unit), 0).label("raw_value"),
        )
        .outerjoin(RawMaterial, RawMaterial.branch_id == Branch.id)
        .group_by(Branch.id, Branch.name)
        .order_by(Branch.name.asc())
        .all()
    )
    finished_rows = (
        db.session.query(
            Branch.id,
            Branch.name,
            func.coalesce(func.sum(ProductVariant.stock * ProductVariant.price), 0).label("finished_value"),
        )
        .outerjoin(ProductVariant, ProductVariant.branch_id == Branch.id)
        .group_by(Branch.id, Branch.name)
        .order_by(Branch.name.asc())
        .all()
    )
    finished_by_branch = {row.id: money(row.finished_value) for row in finished_rows}
    branch_rows = []
    for row in branch_raw_rows:
        raw = money(row.raw_value)
        finished = finished_by_branch.get(row.id, Decimal("0.00"))
        branch_rows.append(
            {
                "branch_id": row.id,
                "branch": row.name,
                "raw_material_value": raw,
                "finished_goods_value": finished,
                "total_value": raw + finished,
            }
        )
    return {
        "raw_material_value": money(raw_value),
        "finished_goods_value": sum((row["finished_goods_value"] for row in branch_rows), Decimal("0.00")),
        "branch_rows": branch_rows,
        "total_value": money(raw_value) + sum((row["finished_goods_value"] for row in branch_rows), Decimal("0.00")),
    }


def branch_financial_rows(period):
    finance = get_container().finance_service
    stores = finance.store_ledger(start_date=period["start_date"], end_date=period["end_date"])
    inventory = {row["branch"]: row["total_value"] for row in inventory_summary()["branch_rows"]}
    total_revenue = sum((money(row["income"]) for row in stores), Decimal("0"))
    rows = []
    for row in stores:
        revenue = money(row["income"])
        expenses = money(row["expenses"])
        rows.append(
            {
                "branch_id": row.get("branch_id"),
                "branch": row["store"],
                "revenue": revenue,
                "orders": revenue_order_query(period).filter(Order.branch_id == row.get("branch_id")).count()
                if row.get("branch_id")
                else 0,
                "average_order_value": Decimal("0.00"),
                "expenses": expenses,
                "gross_contribution": money(row["net"]),
                "inventory_value": inventory.get(row["store"], Decimal("0.00")),
                "contribution_pct": pct_change(revenue, total_revenue - revenue) if total_revenue > 0 else None,
            }
        )
    for row in rows:
        row["average_order_value"] = (
            money(row["revenue"] / row["orders"]) if row["orders"] else Decimal("0.00")
        )
    return rows


def monthly_chart_data(period):
    finance = get_container().finance_service
    labels = []
    revenue = []
    expenses = []
    net_profit = []
    cursor = datetime.combine(period["start_date"].replace(day=1), datetime.min.time())
    end = period["end"]
    while cursor < end:
        month_end = min(cursor + relativedelta(months=1), end)
        payload = finance.profit_and_loss(
            start_date=cursor.date(),
            end_date=(month_end - timedelta(days=1)).date(),
        )
        labels.append(cursor.strftime("%b %Y"))
        revenue.append(float(payload["income"]))
        expenses.append(float(payload["expenses"]))
        net_profit.append(float(payload["net_profit"]))
        cursor = month_end
    return {"labels": labels, "revenue": revenue, "expenses": expenses, "net_profit": net_profit}


def paginate(query):
    page = max(1, request.args.get("page", 1, type=int))
    return query.paginate(page=page, per_page=PAGE_SIZE, error_out=False)


def log_download(report_key, file_format, financial_year):
    db.session.add(
        AuditReportDownload(
            user_id=current_user.id,
            report_key=report_key,
            financial_year=financial_year,
            file_format=file_format,
            portal_context="audit_admin_preview" if is_admin_preview() else "audit",
            ip_address=request.headers.get("X-Forwarded-For", request.remote_addr),
            user_agent=(request.user_agent.string or "")[:200],
        )
    )
    get_container().audit_service.log(
        current_user,
        "auditor_report_download",
        "AuditReport",
        report_key,
        after={
            "report_key": report_key,
            "financial_year": financial_year,
            "file_format": file_format,
        },
        change_summary=f"{AUDIT_REPORTS.get(report_key, report_key)} downloaded from Auditor Portal.",
    )
    db.session.commit()


def send_export(content, mimetype, filename, report_key, file_format, financial_year):
    log_download(report_key, file_format, financial_year)
    return send_file(
        io.BytesIO(content),
        mimetype=mimetype,
        as_attachment=True,
        download_name=filename,
    )


@audit_bp.route("/", methods=["GET", "POST"])
def dashboard():
    period = selected_period()
    previous = previous_period(period)
    finance = get_container().finance_service
    dashboard_payload = finance.dashboard_payload(
        "custom",
        start_date=period["start_date"],
        end_date=period["end_date"],
    )
    previous_pnl = finance.profit_and_loss(
        start_date=previous["start_date"],
        end_date=previous["end_date"],
    )
    inventory = inventory_summary()
    branches = branch_financial_rows(period)
    primary_metrics = [
        {
            "label": "Revenue",
            "value": dashboard_payload["pnl"]["income"],
            "comparison": pct_change(dashboard_payload["pnl"]["income"], previous_pnl["income"]),
        },
        {
            "label": "Net Profit",
            "value": dashboard_payload["pnl"]["net_profit"],
            "comparison": pct_change(dashboard_payload["pnl"]["net_profit"], previous_pnl["net_profit"]),
        },
        {
            "label": "GST Payable",
            "value": dashboard_payload["gst"]["net_gst_liability"],
            "comparison": None,
        },
        {
            "label": "Inventory Value",
            "value": inventory["total_value"],
            "comparison": None,
        },
    ]
    secondary_metrics = [
        {"label": "Sales", "value": dashboard_payload["pnl"]["sales_revenue"]},
        {"label": "Purchases", "value": sum((row["total_spend"] for row in dashboard_payload["vendor_spend"]), Decimal("0"))},
        {"label": "Expenses", "value": dashboard_payload["pnl"]["expenses"]},
        {"label": "Supplier GST", "value": dashboard_payload["gst"]["input_gst_recorded"]},
    ]
    return render_template(
        "audit/dashboard.html",
        dashboard=dashboard_payload,
        primary_metrics=primary_metrics,
        secondary_metrics=secondary_metrics,
        chart_data=monthly_chart_data(period),
        branch_rows=branches,
        inventory=inventory,
        report_catalog=AUDIT_REPORTS,
        **audit_shell_context(),
    )


@audit_bp.route("/sales")
def sales():
    period = selected_period()
    query = branch_filtered_order_query(period).order_by(Order.placed_at.desc(), Order.id.desc())
    pagination = paginate(query)
    return render_template(
        "audit/sales.html",
        pagination=pagination,
        summary=sales_summary(query),
        **audit_shell_context(),
    )


@audit_bp.route("/sales/<int:order_id>")
def sales_detail(order_id):
    order = (
        Order.query.options(
            selectinload(Order.branch),
            selectinload(Order.customer),
        )
        .filter_by(id=order_id)
        .first_or_404()
    )
    return render_template(
        "audit/sales_detail.html",
        order=order,
        order_items=order.items.all(),
        refunds=order.refunds.all(),
        **audit_shell_context(),
    )


@audit_bp.route("/revenue")
def revenue():
    period = selected_period()
    finance = get_container().finance_service
    payload = finance.dashboard_payload(
        "custom",
        start_date=period["start_date"],
        end_date=period["end_date"],
    )
    return render_template(
        "audit/revenue.html",
        payload=payload,
        branch_rows=branch_financial_rows(period),
        chart_data=monthly_chart_data(period),
        **audit_shell_context(),
    )


@audit_bp.route("/revenue/branches/<int:branch_id>")
def branch_revenue_detail(branch_id):
    period = selected_period()
    branch = db.get_or_404(Branch, branch_id)
    orders = revenue_order_query(period).filter(Order.branch_id == branch.id).order_by(Order.placed_at.desc()).limit(50).all()
    expenses = expense_query(period).filter(FinancialTransaction.branch_id == branch.id).order_by(FinancialTransaction.created_at.desc()).limit(50).all()
    inventory = [row for row in inventory_summary()["branch_rows"] if row["branch_id"] == branch.id]
    return render_template(
        "audit/branch_detail.html",
        branch=branch,
        orders=orders,
        expenses=expenses,
        inventory=inventory[0] if inventory else None,
        **audit_shell_context(),
    )


@audit_bp.route("/purchases")
def purchases():
    period = selected_period()
    query = purchase_query(period).order_by(PurchaseOrder.order_date.desc(), PurchaseOrder.id.desc())
    return render_template(
        "audit/purchases.html",
        pagination=paginate(query),
        summary=purchase_summary(query),
        vendors=Vendor.query.order_by(Vendor.name.asc()).all(),
        **audit_shell_context(),
    )


@audit_bp.route("/expenses")
def expenses():
    period = selected_period()
    query = expense_query(period).order_by(FinancialTransaction.created_at.desc(), FinancialTransaction.id.desc())
    return render_template(
        "audit/expenses.html",
        pagination=paginate(query),
        summary=expense_summary(query),
        categories=FinancialCategory.query.filter_by(transaction_type="expense").order_by(FinancialCategory.label.asc()).all(),
        vendors=Vendor.query.order_by(Vendor.name.asc()).all(),
        **audit_shell_context(),
    )


@audit_bp.route("/financial-statements")
def financial_statements():
    return redirect(url_for("audit.profit_loss", **request.args.to_dict(flat=True)))


@audit_bp.route("/financial-statements/profit-loss")
def profit_loss():
    period = selected_period()
    finance = get_container().finance_service
    pnl = finance.profit_and_loss(start_date=period["start_date"], end_date=period["end_date"])
    products = finance.product_ledger(start_date=period["start_date"], end_date=period["end_date"])
    return render_template(
        "audit/profit_loss.html",
        pnl=pnl,
        products=products,
        **audit_shell_context(),
    )


@audit_bp.route("/financial-statements/balance-sheet")
def balance_sheet():
    period = selected_period()
    pnl = get_container().finance_service.profit_and_loss(
        start_date=period["start_date"],
        end_date=period["end_date"],
    )
    inventory = inventory_summary()
    gst = get_container().finance_service.gst_summary(
        start_date=period["start_date"],
        end_date=period["end_date"],
    )
    return render_template(
        "audit/balance_sheet.html",
        pnl=pnl,
        inventory=inventory,
        gst=gst,
        limitation="A full balance sheet needs a chart of accounts, bank balances, fixed assets, liabilities, and equity ledgers. This page only shows supported balances from current Bakery records.",
        **audit_shell_context(),
    )


@audit_bp.route("/financial-statements/trial-balance")
def trial_balance():
    return render_template(
        "audit/unsupported_statement.html",
        title="Trial Balance",
        limitation="The current Bakery schema does not yet include a double-entry chart of accounts with opening/period debit and credit balances. No trial-balance entries are fabricated.",
        **audit_shell_context(),
    )


@audit_bp.route("/financial-statements/general-ledger")
def general_ledger():
    period = selected_period()
    rows = (
        FinancialTransaction.query.options(selectinload(FinancialTransaction.category), selectinload(FinancialTransaction.branch))
        .filter(FinancialTransaction.created_at >= period["start"], FinancialTransaction.created_at < period["end"])
        .order_by(FinancialTransaction.created_at.desc())
        .limit(200)
        .all()
    )
    return render_template(
        "audit/general_ledger.html",
        rows=rows,
        limitation="This is a read-only transaction ledger from Bakery financial transactions, not a full double-entry general ledger.",
        **audit_shell_context(),
    )


@audit_bp.route("/gst")
def gst():
    period = selected_period()
    finance = get_container().finance_service
    summary = finance.gst_summary(start_date=period["start_date"], end_date=period["end_date"])
    tds = finance.tds_summary(start_date=period["start_date"], end_date=period["end_date"])
    return render_template("audit/gst.html", summary=summary, tds=tds, **audit_shell_context())


@audit_bp.route("/bank-cash")
def bank_cash():
    period = selected_period()
    cash_sales = revenue_order_query(period).filter(Order.payment_method.ilike("%cash%")).with_entities(func.coalesce(func.sum(Order.total), 0)).scalar()
    digital_sales = revenue_order_query(period).filter(~Order.payment_method.ilike("%cash%")).with_entities(func.coalesce(func.sum(Order.total), 0)).scalar()
    return render_template(
        "audit/bank_cash.html",
        cash_sales=money(cash_sales),
        digital_sales=money(digital_sales),
        limitation="Dedicated bank account and reconciliation models are not present yet. Bank balances and reconciliation states are not fabricated.",
        **audit_shell_context(),
    )


@audit_bp.route("/receivables")
def receivables():
    period = selected_period()
    rows = branch_filtered_order_query(period).filter(
        ~Order.status.in_(["CANCELLED", "REFUNDED"]),
        Order.payment_status.notin_(["PAID", "REFUNDED"]),
    ).order_by(Order.placed_at.asc()).all()
    total = sum((money(row.total) for row in rows), Decimal("0"))
    return render_template("audit/receivables.html", rows=rows, total=total, **audit_shell_context())


@audit_bp.route("/payables")
def payables():
    period = selected_period()
    rows = [
        po
        for po in purchase_query(period).order_by(PurchaseOrder.order_date.asc()).all()
        if (po.status or "").lower() not in {"received", "closed", "cancelled"}
    ]
    total = sum((money(row.subtotal) for row in rows), Decimal("0"))
    return render_template("audit/payables.html", rows=rows, total=total, **audit_shell_context())


@audit_bp.route("/inventory")
def inventory():
    wastage = (
        StockMovement.query.options(selectinload(StockMovement.raw_material), selectinload(StockMovement.actor))
        .filter(StockMovement.reason.in_(["wastage", "damage", "expired"]))
        .order_by(StockMovement.created_at.desc())
        .limit(100)
        .all()
    )
    return render_template(
        "audit/inventory.html",
        inventory=inventory_summary(),
        wastage=wastage,
        **audit_shell_context(),
    )


@audit_bp.route("/fixed-assets")
def fixed_assets():
    return render_template(
        "audit/unsupported_statement.html",
        title="Fixed Assets",
        limitation="Fixed asset, depreciation, accumulated depreciation, and book-value models are not present yet. This page is reserved for the future fixed-asset register.",
        **audit_shell_context(),
    )


@audit_bp.route("/payroll")
def payroll():
    period = selected_period()
    rows = (
        SalaryRecord.query.options(selectinload(SalaryRecord.branch), selectinload(SalaryRecord.user))
        .filter(SalaryRecord.period_start <= period["end_date"], SalaryRecord.period_end >= period["start_date"])
        .order_by(SalaryRecord.period_start.desc())
        .all()
    )
    total = sum((money(row.amount) for row in rows), Decimal("0"))
    return render_template("audit/payroll.html", rows=rows, total=total, **audit_shell_context())


@audit_bp.route("/branches")
def branches():
    period = selected_period()
    return render_template(
        "audit/branches.html",
        rows=branch_financial_rows(period),
        chart_data=monthly_chart_data(period),
        **audit_shell_context(),
    )


@audit_bp.route("/requirements", methods=["GET", "POST"])
def requirements():
    period = selected_period()
    if request.method == "POST":
        title = (request.form.get("title") or "").strip()
        description = (request.form.get("description") or "").strip()
        category = (request.form.get("category") or "Other").strip()
        priority = (request.form.get("priority") or "NORMAL").strip().upper()
        if category not in AUDIT_REQUIREMENT_CATEGORIES:
            category = "Other"
        if priority not in AUDIT_REQUIREMENT_PRIORITIES:
            priority = "NORMAL"
        if not title or not description:
            flash("Requirement title and description are required.", "danger")
            return redirect(url_for("audit.requirements", financial_year=period["financial_year"]))
        due_date = None
        due_raw = (request.form.get("due_date") or "").strip()
        if due_raw:
            try:
                due_date = date.fromisoformat(due_raw)
            except ValueError:
                flash("Requested due date is invalid.", "danger")
                return redirect(url_for("audit.requirements", financial_year=period["financial_year"]))
        requirement = AuditorRequirement(
            requirement_uid=audit_requirement_uid(),
            auditor_id=current_user.id,
            requested_by=current_user.id,
            financial_year=request.form.get("financial_year") or period["financial_year"],
            period_label=(request.form.get("period_label") or "").strip() or None,
            title=title,
            description=description,
            category=category,
            priority=priority,
            status="OPEN",
            due_date=due_date,
            requested_at=utcnow(),
            created_at=utcnow(),
            updated_at=utcnow(),
        )
        db.session.add(requirement)
        db.session.flush()
        audit_requirement_event(requirement, "auditor_requested", description)
        get_container().audit_service.log(
            current_user,
            "auditor_requirement_created",
            "AuditorRequirement",
            requirement.id,
            after={
                "requirement_uid": requirement.requirement_uid,
                "category": requirement.category,
                "priority": requirement.priority,
            },
            change_summary=f"Auditor created requirement {requirement.requirement_uid}.",
        )
        db.session.commit()
        flash("Requirement sent to Admin Audit Management.", "success")
        return redirect(url_for("audit.requirement_detail", requirement_id=requirement.id))

    query = AuditorRequirement.query.options(
        selectinload(AuditorRequirement.documents),
    )
    if has_role(current_user, "auditor"):
        query = query.filter(AuditorRequirement.auditor_id == current_user.id)
    query = query.filter(AuditorRequirement.financial_year == period["financial_year"])
    status = (request.args.get("status") or "").strip().upper()
    if status in AUDIT_REQUIREMENT_STATUSES:
        query = query.filter(AuditorRequirement.status == status)
    return render_template(
        "audit/requirements.html",
        requirements=query.order_by(AuditorRequirement.updated_at.desc()).limit(50).all(),
        categories=AUDIT_REQUIREMENT_CATEGORIES,
        priorities=AUDIT_REQUIREMENT_PRIORITIES,
        statuses=AUDIT_REQUIREMENT_STATUSES,
        **audit_shell_context(),
    )


@audit_bp.route("/requirements/<int:requirement_id>")
def requirement_detail(requirement_id):
    requirement = auditor_requirement_or_404(requirement_id)
    visible_documents = [
        document for document in requirement.documents if document.is_auditor_visible
    ]
    return render_template(
        "audit/requirement_detail.html",
        requirement=requirement,
        visible_documents=visible_documents,
        **audit_shell_context(),
    )


@audit_bp.route("/requirements/<int:requirement_id>/revision", methods=["POST"])
def request_revision(requirement_id):
    requirement = auditor_requirement_or_404(requirement_id)
    comment = (request.form.get("comment") or "").strip()
    if not comment:
        flash("Add a revision comment before sending.", "danger")
        return redirect(url_for("audit.requirement_detail", requirement_id=requirement.id))
    before = {"status": requirement.status, "latest_auditor_comment": requirement.latest_auditor_comment}
    requirement.status = "NEEDS_REVISION"
    requirement.latest_auditor_comment = comment
    requirement.reviewed_at = utcnow()
    requirement.updated_at = utcnow()
    audit_requirement_event(requirement, "auditor_requested_revision", comment)
    get_container().audit_service.log(
        current_user,
        "auditor_requirement_revision_requested",
        "AuditorRequirement",
        requirement.id,
        before=before,
        after={"status": requirement.status},
        change_summary=f"Auditor requested revision for {requirement.requirement_uid}.",
    )
    db.session.commit()
    flash("Revision request sent to Admin Audit Management.", "success")
    return redirect(url_for("audit.requirement_detail", requirement_id=requirement.id))


@audit_bp.route("/requirements/<int:requirement_id>/resolve", methods=["POST"])
def resolve_requirement(requirement_id):
    requirement = auditor_requirement_or_404(requirement_id)
    before = {"status": requirement.status}
    requirement.status = "RESOLVED"
    requirement.reviewed_at = utcnow()
    requirement.resolved_at = utcnow()
    requirement.updated_at = utcnow()
    audit_requirement_event(
        requirement,
        "auditor_resolved",
        (request.form.get("comment") or "Requirement resolved.").strip(),
    )
    get_container().audit_service.log(
        current_user,
        "auditor_requirement_resolved",
        "AuditorRequirement",
        requirement.id,
        before=before,
        after={"status": requirement.status},
        change_summary=f"Auditor resolved requirement {requirement.requirement_uid}.",
    )
    db.session.commit()
    flash("Requirement marked resolved.", "success")
    return redirect(url_for("audit.requirement_detail", requirement_id=requirement.id))


@audit_bp.route("/documents")
def documents():
    query = AuditDocument.query.options(
        selectinload(AuditDocument.uploader),
        selectinload(AuditDocument.requirement),
    ).filter_by(
        status="PUBLISHED",
        visibility="AUDITOR",
    )
    if has_role(current_user, "auditor"):
        query = query.outerjoin(AuditorRequirement).filter(
            or_(
                AuditDocument.requirement_id.is_(None),
                AuditorRequirement.auditor_id == current_user.id,
            )
        )
    category = (request.args.get("category") or "").strip()
    if category:
        query = query.filter(AuditDocument.category == category)
    financial_year = request.args.get("financial_year")
    if financial_year:
        query = query.filter(AuditDocument.financial_year == financial_year)
    search = (request.args.get("q") or "").strip()
    if search:
        query = query.filter(AuditDocument.title.ilike(f"%{search}%"))
    return render_template(
        "audit/documents.html",
        documents=query.order_by(AuditDocument.uploaded_at.desc()).all(),
        categories=AUDIT_DOCUMENT_CATEGORIES,
        **audit_shell_context(),
    )


@audit_bp.route("/documents/<document_uid>/download")
def download_document(document_uid):
    document = (
        AuditDocument.query.options(selectinload(AuditDocument.requirement))
        .filter_by(document_uid=document_uid)
        .first_or_404()
    )
    if not document.is_auditor_visible:
        abort(404)
    if (
        has_role(current_user, "auditor")
        and document.requirement is not None
        and document.requirement.auditor_id != current_user.id
    ):
        abort(404)
    safe_reference = secure_filename(document.storage_reference or "")
    if safe_reference != (document.storage_reference or ""):
        abort(404)
    root = current_app.config.get("AUDIT_DOCUMENT_STORAGE_ROOT")
    base = Path(root) if root else Path(current_app.instance_path) / "audit_documents"
    target = base / safe_reference
    if not target.exists():
        abort(404)
    db.session.add(
        AuditReportDownload(
            user_id=current_user.id,
            report_key=f"audit-document:{document.document_uid}",
            financial_year=document.financial_year,
            file_format=(document.original_filename or "").rsplit(".", 1)[-1] or "file",
            portal_context="audit_admin_preview" if is_admin_preview() else "audit",
            ip_address=request.remote_addr,
            user_agent=(request.user_agent.string or "")[:200],
        )
    )
    get_container().audit_service.log(
        current_user,
        "auditor_document_download",
        "AuditDocument",
        document.id,
        change_summary=f"Auditor downloaded audit document: {document.title}.",
    )
    db.session.commit()
    return send_file(
        target,
        as_attachment=True,
        download_name=document.original_filename or target.name,
        mimetype=document.mime_type,
    )


@audit_bp.route("/reports")
def reports():
    return render_template("audit/reports.html", report_catalog=AUDIT_REPORTS, **audit_shell_context())


@audit_bp.route("/reports/<report_key>.<file_format>")
def download_report(report_key, file_format):
    if report_key not in AUDIT_REPORTS:
        abort(404)
    file_format = (file_format or "csv").lower()
    if file_format not in {"csv", "pdf"}:
        abort(404)
    period = selected_period()
    finance = get_container().finance_service
    export = get_container().finance_export_service

    rows = []
    headers = ["Metric", "Value"]
    title = AUDIT_REPORTS[report_key]
    if report_key == "sales-register":
        headers = ["Invoice", "Date", "Branch", "Customer", "Payment", "Status", "Taxable", "GST", "Total"]
        for order in branch_filtered_order_query(period).order_by(Order.placed_at.desc()).limit(1000).all():
            rows.append([
                order.invoice_number or order.order_number,
                order.placed_at.date() if order.placed_at else "",
                order.branch.name if order.branch else "",
                order.customer.name if order.customer else "",
                order.payment_method,
                order.payment_status,
                order.gst_taxable_amount,
                order.gst_amount,
                order.total,
            ])
    elif report_key == "purchase-register":
        headers = ["PO", "Date", "Vendor", "GSTIN", "Status", "Taxable", "GST", "Total"]
        for po in purchase_query(period).limit(1000).all():
            gst_amount = money(po.subtotal) * Decimal(str(po.gst_rate_percent or 0)) / Decimal("100")
            rows.append([f"PO-{po.id}", po.order_date, po.vendor.name if po.vendor else "", po.vendor.gstin if po.vendor else "", po.status, po.subtotal, gst_amount, money(po.subtotal) + gst_amount])
    elif report_key == "expense-register":
        headers = ["Date", "Category", "Branch", "Counterparty", "Amount", "GST", "Payment"]
        for txn in expense_query(period).limit(1000).all():
            rows.append([txn.created_at.date(), txn.category.label if txn.category else "", txn.branch.name if txn.branch else "", txn.counterparty or "", txn.amount, txn.tax_amount or 0, txn.payment_method or ""])
    elif report_key == "gst-report":
        gst = finance.gst_summary(start_date=period["start_date"], end_date=period["end_date"])
        rows = [["GST Collected", gst["gst_collected"]], ["Input GST Recorded", gst["input_gst_recorded"]], ["Net GST Liability", gst["net_gst_liability"]]]
    elif report_key == "profit-and-loss":
        pnl = finance.profit_and_loss(start_date=period["start_date"], end_date=period["end_date"])
        rows = [["Income", pnl["income"]], ["Expenses", pnl["expenses"]], ["Net Profit", pnl["net_profit"]]]
    elif report_key == "inventory-valuation":
        inv = inventory_summary()
        rows = [["Raw Material Value", inv["raw_material_value"]], ["Finished Goods Value", inv["finished_goods_value"]], ["Total Inventory Value", inv["total_value"]]]
    elif report_key == "branch-financial-report":
        headers = ["Branch", "Revenue", "Orders", "Expenses", "Gross Contribution", "Inventory Value"]
        rows = [[row["branch"], row["revenue"], row["orders"], row["expenses"], row["gross_contribution"], row["inventory_value"]] for row in branch_financial_rows(period)]
    elif report_key == "cash-summary":
        rows = [["Cash Sales", revenue_order_query(period).filter(Order.payment_method.ilike("%cash%")).with_entities(func.coalesce(func.sum(Order.total), 0)).scalar() or 0]]
    else:
        pnl = finance.profit_and_loss(start_date=period["start_date"], end_date=period["end_date"])
        rows = [["Revenue", pnl["income"]], ["Expenses", pnl["expenses"]]]

    if file_format == "pdf":
        content = export.simple_pdf(title, [f"{headers[0]}: {headers[1]}", f"Period: {period['label']}", ""] + [", ".join(str(item) for item in row) for row in rows[:120]])
        return send_export(content, "application/pdf", f"{report_key}_{period['start_date']}_{period['end_date']}.pdf", report_key, "pdf", period["financial_year"])
    content = export.rows_csv(headers, rows)
    return send_export(content, "text/csv", f"{report_key}_{period['start_date']}_{period['end_date']}.csv", report_key, "csv", period["financial_year"])
