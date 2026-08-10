import json
from decimal import Decimal

from clock import utcnow
from models import AuditLog, Order, PosPaymentTransaction, User, db


def sign_in(test_client, email="admin@bakery.com", password="Admin@bakery"):
    return test_client.post(
        "/auth/login",
        data={"email": email, "password": password},
        follow_redirects=False,
    )


def test_pos_terminal_requires_admin_employee(admin_client):
    response = admin_client.get("/admin/pos/terminal")
    assert response.status_code == 302
    assert "/auth/login" in response.headers["Location"]


def test_pos_terminal_blocks_employee_without_pos_section(
    admin_client,
    admin_app,
):
    with admin_app.app_context():
        user = User(
            name="No POS",
            email="no-pos@example.com",
            role="admin",
            admin_tier="staff",
            is_active=True,
        )
        user.set_password("NoPos123")
        user.permissions = json.dumps(["dashboard"])
        db.session.add(user)
        db.session.commit()

    assert sign_in(admin_client, "no-pos@example.com", "NoPos123").status_code == 302
    response = admin_client.get("/admin/pos/terminal")
    assert response.status_code == 403


def test_pos_terminal_records_cash_payment_and_change(admin_client, admin_app):
    assert sign_in(admin_client).status_code == 302
    response = admin_client.post(
        "/admin/pos/terminal",
        data={
            "idempotency_key": "cash-key-1",
            "amount": "525.00",
            "payment_method": "CASH",
            "cash_received": "600.00",
        },
        follow_redirects=False,
    )

    assert response.status_code == 302
    with admin_app.app_context():
        transaction = PosPaymentTransaction.query.filter_by(
            idempotency_key="cash-key-1"
        ).one()
        assert transaction.amount == Decimal("525.00")
        assert transaction.cash_received == Decimal("600.00")
        assert transaction.change_returned == Decimal("75.00")
        assert transaction.payment_status == "COMPLETED"
        assert transaction.cashier.email == "admin@bakery.com"
        assert AuditLog.query.filter_by(action="pos_mvp_payment_completed").count() == 1


def test_pos_terminal_rejects_underpaid_cash(admin_client, admin_app):
    sign_in(admin_client)
    response = admin_client.post(
        "/admin/pos/terminal",
        data={
            "idempotency_key": "cash-key-underpaid",
            "amount": "525.00",
            "payment_method": "CASH",
            "cash_received": "500.00",
        },
    )

    assert response.status_code == 200
    assert b"Cash received is less than the amount payable" in response.data
    with admin_app.app_context():
        assert PosPaymentTransaction.query.filter_by(
            idempotency_key="cash-key-underpaid"
        ).count() == 0
        assert AuditLog.query.filter_by(action="pos_mvp_payment_failed").count() == 1


def test_pos_terminal_records_upi_reference_once(admin_client, admin_app):
    sign_in(admin_client)
    payload = {
        "idempotency_key": "upi-key-1",
        "amount": "250.50",
        "payment_method": "UPI",
        "transaction_reference": "UPI-REF-123",
        "upi_app": "PhonePe",
    }
    first = admin_client.post("/admin/pos/terminal", data=payload)
    second = admin_client.post("/admin/pos/terminal", data=payload)

    assert first.status_code == 302
    assert second.status_code == 302
    with admin_app.app_context():
        assert PosPaymentTransaction.query.filter_by(
            idempotency_key="upi-key-1"
        ).count() == 1
        transaction = PosPaymentTransaction.query.filter_by(
            idempotency_key="upi-key-1"
        ).one()
        assert transaction.transaction_reference == "UPI-REF-123"
        assert "PhonePe" in transaction.method_details_json


def test_pos_terminal_uses_server_order_amount(admin_client, admin_app):
    with admin_app.app_context():
        customer = User.query.filter_by(email="customer@test.com").first()
        order = Order(
            order_number=Order.generate_order_number(),
            user_id=customer.id,
            status="PLACED",
            subtotal=Decimal("375.00"),
            total=Decimal("375.00"),
            payment_status="PENDING",
            address_line1="1 Test Street",
            city="Coimbatore",
            pincode="641002",
            phone="9999999999",
            delivery_slot="Walk-in",
            delivery_date=utcnow().date(),
        )
        db.session.add(order)
        db.session.commit()
        order_number = order.order_number

    sign_in(admin_client)
    response = admin_client.post(
        "/admin/pos/terminal",
        data={
            "idempotency_key": "order-key-1",
            "order_number": order_number,
            "amount": "1.00",
            "payment_method": "UPI",
            "transaction_reference": "ORDER-UPI-1",
        },
    )

    assert response.status_code == 302
    with admin_app.app_context():
        transaction = PosPaymentTransaction.query.filter_by(
            idempotency_key="order-key-1"
        ).one()
        assert transaction.amount == Decimal("375.00")
        assert transaction.order.payment_status == "PAID"
        assert transaction.payment.status == "PAID"
