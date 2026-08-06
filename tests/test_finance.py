"""Finance module tests."""

from decimal import Decimal

from models import (
    FinancialCategory,
    FinancialTransaction,
    GST_LIABILITY_BAKERY,
    GST_LIABILITY_ECOMMERCE_OPERATOR,
    GST_ORDER_SOURCE_COUNTER_TAKEAWAY,
    GST_ORDER_SOURCE_ECOMMERCE_ZOMATO,
    GST_RETURN_ECOMMERCE_9_5,
    GST_RETURN_OUTWARD_SUPPLIES,
    Order,
    Payment,
    Product,
    ProductMaterial,
    RawMaterial,
    User,
    db,
)
from services.finance_service import FinanceService


def sign_in(test_client, email, password):
    return test_client.post(
        "/auth/login",
        data={"email": email, "password": password},
        follow_redirects=False,
    )


def test_finance_dashboard_requires_admin_role(admin_client):
    sign_in(admin_client, "admin@bakery.com", "Admin@bakery")
    response = admin_client.get("/admin/finance")
    assert response.status_code == 200
    assert b"Finance Command Center" in response.data
    assert b"finance-custom-range" in response.data
    assert b"Custom date range" in response.data
    assert b"Record-keeping aid only" in response.data
    assert b"Sales Performance" in response.data
    assert b"Financial Health at a Glance" in response.data


def test_gst_summary_page_renders_channel_reporting(admin_client):
    sign_in(admin_client, "admin@bakery.com", "Admin@bakery")
    response = admin_client.get("/admin/finance/gst?period=month")
    assert response.status_code == 200
    assert b"GST Summary" in response.data
    assert b"GSTR-1 Mapping" in response.data
    assert b"Order-wise GST Export Preview" in response.data
    assert b"GST Payable by Bakery" in response.data


def test_tax_rates_page_has_finance_back_action(admin_client):
    sign_in(admin_client, "admin@bakery.com", "Admin@bakery")
    response = admin_client.get("/admin/finance/tax-rates")
    assert response.status_code == 200
    assert b"Back to Finance" in response.data
    assert b'href="/admin/finance"' in response.data
    assert b'data-toggle-target="#add-tax-rate-form"' in response.data
    assert b'id="add-tax-rate-form" class="card hidden"' in response.data


def test_cashier_cannot_access_finance(admin_client):
    with admin_client.application.app_context():
        user = User.query.filter_by(email="admin@bakery.com").first()
        user.role = "cashier"
        db.session.commit()

    sign_in(admin_client, "admin@bakery.com", "Admin@bakery")
    response = admin_client.get("/admin/finance")
    assert response.status_code == 403

    with admin_client.application.app_context():
        user = User.query.filter_by(email="admin@bakery.com").first()
        user.role = "admin"
        user.admin_tier = "owner"
        db.session.commit()


def test_payment_paid_creates_sale_transaction(admin_client):
    with admin_client.application.app_context():
        customer = User.query.filter_by(email="customer@test.com").first()
        order = Order(
            order_number=Order.generate_order_number(),
            user_id=customer.id,
            status="DELIVERED",
            subtotal=Decimal("200"),
            total=Decimal("200"),
            payment_status="PENDING",
            address_line1="1 Test Lane",
            city="Coimbatore",
            pincode="641002",
            phone="9999999999",
            delivery_slot="09:00 - 11:00",
        )
        db.session.add(order)
        db.session.flush()
        payment = Payment(
            order_id=order.id, amount=Decimal("200"), status="PENDING", method="COD"
        )
        db.session.add(payment)
        db.session.commit()
        order_id = order.id

        FinanceService().ensure_default_categories()
        payment.transition_to("PAID", reason="test")
        db.session.commit()

        txn = FinancialTransaction.query.filter_by(reference_order_id=order_id).first()
        assert txn is not None
        assert txn.transaction_type == "income"
        assert Decimal(str(txn.amount)) == Decimal("200")
        assert txn.is_auto_generated is True


def test_manual_expense_roundtrip_encrypted(admin_client):
    sign_in(admin_client, "admin@bakery.com", "Admin@bakery")
    with admin_client.application.app_context():
        FinanceService().ensure_default_categories()
        category = FinancialCategory.query.filter_by(code="rent").first()
        assert category is not None
        category_id = category.id

    response = admin_client.post(
        "/admin/finance/transactions/add",
        data={
            "transaction_type": "expense",
            "category_id": str(category_id),
            "amount": "15000",
            "tax_amount": "2700",
            "description": "July shop rent",
            "counterparty": "Landlord LLC",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"Financial transaction recorded" in response.data

    with admin_client.application.app_context():
        txn = FinancialTransaction.query.order_by(
            FinancialTransaction.id.desc()
        ).first()
        assert txn is not None
        assert Decimal(str(txn.amount)) == Decimal("15000")
        assert txn.description == "July shop rent"
        assert txn.counterparty == "Landlord LLC"


def test_product_ledger_page_renders(admin_client):
    sign_in(admin_client, "admin@bakery.com", "Admin@bakery")
    with admin_client.application.app_context():
        product = Product(name="Ledger Cake", base_price=500, is_active=True)
        material = RawMaterial(
            name="Ledger Flour", unit="kg", cost_per_unit=Decimal("40")
        )
        db.session.add_all([product, material])
        db.session.flush()
        db.session.add(
            ProductMaterial(
                product_id=product.id,
                raw_material_id=material.id,
                quantity_required=Decimal("0.5"),
            )
        )
        db.session.commit()

    response = admin_client.get("/admin/finance/ledger/products")
    assert response.status_code == 200
    assert b"Product Ledger" in response.data


def test_finance_dashboard_exports_unified_sections(admin_client):
    sign_in(admin_client, "admin@bakery.com", "Admin@bakery")

    dashboard_csv = admin_client.get("/admin/finance/export/dashboard/csv?period=month")
    assert dashboard_csv.status_code == 200
    assert dashboard_csv.mimetype == "text/csv"
    assert b"Sales Revenue" in dashboard_csv.data
    assert b"Revenue Consistency Difference" in dashboard_csv.data

    sales_csv = admin_client.get("/admin/finance/export/sales/csv?period=month")
    assert sales_csv.status_code == 200
    assert sales_csv.mimetype == "text/csv"
    assert b"Units Sold" in sales_csv.data

    gst_csv = admin_client.get("/admin/finance/export/gst/csv?period=month")
    assert gst_csv.status_code == 200
    assert gst_csv.mimetype == "text/csv"
    assert b"Order Date,Invoice Number,Order Source,Base Taxable Value" in gst_csv.data


def test_gst_summary_splits_bakery_and_ecommerce_liability(admin_client):
    with admin_client.application.app_context():
        customer = User.query.filter_by(email="customer@test.com").first()
        counter_order = Order(
            order_number=Order.generate_order_number(),
            invoice_number="INV-COUNTER-GST",
            user_id=customer.id,
            status="DELIVERED",
            payment_status="PAID",
            channel="counter",
            source="POS",
            subtotal=Decimal("100"),
            gst_taxable_amount=Decimal("100"),
            gst_rate=Decimal("5"),
            cgst_amount=Decimal("2.50"),
            sgst_amount=Decimal("2.50"),
            gst_amount=Decimal("5"),
            total=Decimal("105"),
            gst_order_source=GST_ORDER_SOURCE_COUNTER_TAKEAWAY,
            gst_liability_party=GST_LIABILITY_BAKERY,
            gst_return_bucket=GST_RETURN_OUTWARD_SUPPLIES,
            address_line1="1 Test Lane",
            city="Coimbatore",
            pincode="641002",
            phone="9999999999",
            delivery_slot="Walk-in",
        )
        ecommerce_order = Order(
            order_number=Order.generate_order_number(),
            invoice_number="INV-ZOMATO-GST",
            user_id=customer.id,
            status="DELIVERED",
            payment_status="PAID",
            channel="counter",
            source="ZOMATO",
            subtotal=Decimal("200"),
            gst_taxable_amount=Decimal("200"),
            gst_rate=Decimal("5"),
            cgst_amount=Decimal("5"),
            sgst_amount=Decimal("5"),
            gst_amount=Decimal("10"),
            total=Decimal("210"),
            gst_order_source=GST_ORDER_SOURCE_ECOMMERCE_ZOMATO,
            gst_liability_party=GST_LIABILITY_ECOMMERCE_OPERATOR,
            gst_return_bucket=GST_RETURN_ECOMMERCE_9_5,
            ecommerce_operator="ZOMATO",
            ecommerce_tcs_amount=Decimal("2"),
            gst_invoice_note="Tax to be deposited by E-commerce Operator under Section 9(5) of the CGST Act.",
            address_line1="1 Test Lane",
            city="Coimbatore",
            pincode="641002",
            phone="9999999999",
            delivery_slot="Aggregator",
        )
        db.session.add_all([counter_order, ecommerce_order])
        db.session.commit()

        today = counter_order.placed_at.date()
        summary = FinanceService().gst_summary(start_date=today, end_date=today)

    assert summary["regular_outward_taxable"] == Decimal("100.00")
    assert summary["gst_collected"] == Decimal("5.00")
    assert summary["ecommerce_taxable"] == Decimal("200.00")
    assert summary["ecommerce_operator_gst"] == Decimal("10.00")
    assert summary["ecommerce_tcs"] == Decimal("2.00")
    assert summary["net_gst_liability"] == Decimal("5.00")
    assert {
        row["invoice_number"]: row["tax_liability_flag"] for row in summary["rows"]
    } == {
        "INV-COUNTER-GST": "Payable by Bakery",
        "INV-ZOMATO-GST": "Paid by Aggregator",
    }


def test_finance_consistency_check_flags_missing_sale_transaction(admin_client):
    sign_in(admin_client, "admin@bakery.com", "Admin@bakery")
    with admin_client.application.app_context():
        customer = User.query.filter_by(email="customer@test.com").first()
        order = Order(
            order_number=Order.generate_order_number(),
            user_id=customer.id,
            status="DELIVERED",
            subtotal=Decimal("300"),
            total=Decimal("300"),
            payment_status="PAID",
            address_line1="1 Test Lane",
            city="Coimbatore",
            pincode="641002",
            phone="9999999999",
            delivery_slot="09:00 - 11:00",
        )
        db.session.add(order)
        db.session.commit()

    response = admin_client.post(
        "/admin/finance/consistency-check?period=month",
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert b"Revenue consistency warning" in response.data


def test_backfill_missing_sale_transactions_creates_idempotent_rows(admin_client):
    with admin_client.application.app_context():
        customer = User.query.filter_by(email="customer@test.com").first()
        order = Order(
            order_number=Order.generate_order_number(),
            user_id=customer.id,
            status="DELIVERED",
            subtotal=Decimal("450"),
            total=Decimal("450"),
            payment_status="PAID",
            address_line1="1 Test Lane",
            city="Coimbatore",
            pincode="641002",
            phone="9999999999",
            delivery_slot="09:00 - 11:00",
        )
        db.session.add(order)
        db.session.commit()
        order_id = order.id

        result = FinanceService().backfill_missing_sale_transactions(commit=True)
        assert order_id in result["order_ids"]

        second = FinanceService().backfill_missing_sale_transactions(commit=True)
        assert order_id not in second["order_ids"]
        assert (
            FinancialTransaction.query.filter_by(reference_order_id=order_id).count()
            == 1
        )
