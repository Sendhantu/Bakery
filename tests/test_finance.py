"""Finance module tests."""

from decimal import Decimal

from models import (
    FinancialCategory,
    FinancialTransaction,
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
    assert b"Finance" in response.data
    assert b"Record-keeping aid only" in response.data


def test_cashier_cannot_access_finance(admin_client):
    with admin_client.application.app_context():
        user = User.query.filter_by(email="admin@bakery.com").first()
        user.role = "cashier"
        db.session.commit()

    sign_in(admin_client, "admin@bakery.com", "Admin@bakery")
    response = admin_client.get("/admin/finance")
    assert response.status_code == 302

    with admin_client.application.app_context():
        user = User.query.filter_by(email="admin@bakery.com").first()
        user.role = "admin"
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
        payment = Payment(order_id=order.id, amount=Decimal("200"), status="PENDING", method="COD")
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
        txn = FinancialTransaction.query.order_by(FinancialTransaction.id.desc()).first()
        assert txn is not None
        assert Decimal(str(txn.amount)) == Decimal("15000")
        assert txn.description == "July shop rent"
        assert txn.counterparty == "Landlord LLC"


def test_product_ledger_page_renders(admin_client):
    sign_in(admin_client, "admin@bakery.com", "Admin@bakery")
    with admin_client.application.app_context():
        product = Product(name="Ledger Cake", base_price=500, is_active=True)
        material = RawMaterial(name="Ledger Flour", unit="kg", cost_per_unit=Decimal("40"))
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
