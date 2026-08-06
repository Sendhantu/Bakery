import json
from decimal import Decimal

from clock import utcnow
from exceptions import ValidationError
from models import (
    FinancialTransaction,
    Order,
    ProductVariant,
    RawMaterial,
    StockMovement,
    User,
    db,
)


def sign_in(test_client, email, password):
    return test_client.post(
        "/auth/login",
        data={"email": email, "password": password},
        follow_redirects=False,
    )


def test_order_screen_login_is_scoped_to_walkin_pos(
    admin_client,
    product_factory,
):
    product, variant = product_factory(
        name="Order Screen Quick Cake",
        price=Decimal("90"),
        variant_stock=4,
    )
    variant.sku = "QCK-ORDER"
    variant.barcode = "ORDER-BAR-1"
    db.session.commit()

    login_response = sign_in(admin_client, "order@bakery.com", "screen")

    assert login_response.status_code == 302
    assert login_response.headers["Location"].endswith("/admin/pos")

    pos_response = admin_client.get("/admin/pos")
    assert pos_response.status_code == 200
    assert b"Order screen login" in pos_response.data
    assert b"Quick Add Item" in pos_response.data
    assert b"data-pos-lookup" in pos_response.data
    assert f"Product ID #{product.id}".encode() in pos_response.data
    assert f"Item ID #{variant.id}".encode() in pos_response.data
    assert b"QCK-ORDER" in pos_response.data
    assert b"Update availability / details" not in pos_response.data
    assert b"Vendors" not in pos_response.data

    dashboard_response = admin_client.get("/admin/", follow_redirects=False)
    assert dashboard_response.status_code == 302
    assert dashboard_response.headers["Location"].endswith("/admin/pos")

    blocked_response = admin_client.get("/admin/vendors")
    assert blocked_response.status_code == 403


def test_order_screen_user_can_create_counter_bill_and_choose_payment(
    admin_client,
    product_factory,
):
    _product, variant = product_factory(
        name="Order Screen Pay Bun",
        price=Decimal("70"),
        variant_stock=3,
    )
    db.session.commit()
    sign_in(admin_client, "order@bakery.com", "screen")

    response = admin_client.post(
        "/admin/pos",
        data={
            "cart_items": json.dumps([{"variant_id": variant.id, "quantity": 2}]),
            f"expected_version_{variant.id}": str(variant.version),
            "payment_mode": "UPI",
            "sale_status": "DELIVERED",
            "customer_name": "Walk-in UPI Guest",
            "customer_phone": "9000007777",
        },
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/payment")
    with admin_client.application.app_context():
        order = Order.query.filter_by(channel="counter").order_by(Order.id.desc()).first()
        assert order is not None
        assert order.payment_method == "UPI"
        assert order.payment_status == "PENDING"
        assert order.status == "PLACED"
        assert order.items.count() == 1


def test_counter_sale_uses_shared_order_pipeline_and_emits(
    admin_client,
    raw_material_factory,
    product_factory,
    socket_emit_spy,
    monkeypatch,
):
    flour = raw_material_factory(name="POS Flour", stock=Decimal("5"))
    product, variant = product_factory(
        name="POS Brownie",
        price=Decimal("50"),
        variant_stock=3,
        recipe=[(flour, Decimal("1"))],
    )
    db.session.commit()
    order_service = admin_client.application.extensions[
        "service_container"
    ].order_service
    original_create_order = order_service.create_order
    create_order_calls = []

    def spy_create_order(*args, **kwargs):
        create_order_calls.append(kwargs)
        return original_create_order(*args, **kwargs)

    monkeypatch.setattr(order_service, "create_order", spy_create_order)
    sign_in(admin_client, "admin@bakery.com", "Admin@bakery")

    response = admin_client.post(
        "/admin/pos",
        data={
            "cart_items": json.dumps([{"variant_id": variant.id, "quantity": 2}]),
            f"expected_version_{variant.id}": str(variant.version),
            "payment_mode": "CASH",
            "sale_status": "DELIVERED",
            "customer_name": "Counter Guest",
            "customer_phone": "9000001111",
        },
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert "/admin/pos/orders/" in response.headers["Location"]
    assert response.headers["Location"].endswith("/payment")
    assert create_order_calls
    assert create_order_calls[0]["channel"] == "counter"
    assert create_order_calls[0]["payment_status"] == "PENDING"
    assert create_order_calls[0]["status"] == "PLACED"

    with admin_client.application.app_context():
        order = (
            Order.query.filter_by(channel="counter").order_by(Order.id.desc()).first()
        )
        assert order is not None
        order_id = order.id

    locked_receipt_response = admin_client.get(
        f"/admin/pos/orders/{order_id}/receipt",
        follow_redirects=False,
    )
    assert locked_receipt_response.status_code == 302
    assert locked_receipt_response.headers["Location"].endswith("/payment")

    payment_screen = admin_client.get(response.headers["Location"])
    assert payment_screen.status_code == 200
    assert b"Amount Received" in payment_screen.data
    assert b"Receipt generation is disabled until payment is marked as received" in payment_screen.data

    payment_response = admin_client.post(
        f"/admin/pos/orders/{order_id}/payment",
        data={
            "amount_received": "120",
            "payment_method": "CASH",
            "final_status": "DELIVERED",
            "payment_reference": "PHONE-OK-1",
        },
        follow_redirects=False,
    )
    assert payment_response.status_code == 302
    assert payment_response.headers["Location"].endswith("/receipt")

    receipt_response = admin_client.get(payment_response.headers["Location"])
    assert receipt_response.status_code == 200
    assert receipt_response.mimetype in {"application/pdf", "text/html"}
    if receipt_response.mimetype == "text/html":
        assert b"SweetCrumbs Receipt" in receipt_response.data
    with admin_client.application.app_context():
        order = db.session.get(Order, order_id)
        assert order is not None
        assert order.source == "POS"
        assert order.status == "DELIVERED"
        assert order.payment_status == "PAID"
        assert order.fulfillment_type == "PICKUP"
        assert Decimal(str(order.subtotal)) == Decimal("100.00")
        assert Decimal(str(order.gst_taxable_amount)) == Decimal("100.00")
        assert Decimal(str(order.cgst_amount)) == Decimal("2.50")
        assert Decimal(str(order.sgst_amount)) == Decimal("2.50")
        assert Decimal(str(order.gst_amount)) == Decimal("5.00")
        assert Decimal(str(order.total)) == Decimal("105.00")
        assert order.items.count() == 1
        assert order.payment is not None
        assert order.payment.status == "PAID"
        assert order.payment.gateway_name == "manual_phone"
        payment_payload = json.loads(order.payment.gateway_payload)
        assert payment_payload["amount_received"] == "120.00"
        assert payment_payload["change_due"] == "15.00"

        reloaded_variant = db.session.get(ProductVariant, variant.id)
        reloaded_flour = db.session.get(RawMaterial, flour.id)
        assert reloaded_variant.stock == 1
        assert Decimal(str(reloaded_flour.stock)) == Decimal("3.00")
        assert (
            StockMovement.query.filter_by(
                reference_order_id=order.id,
                reason="order_deduction",
            ).count()
            == 1
        )

        txn = FinancialTransaction.query.filter_by(reference_order_id=order.id).first()
        assert txn is not None
        assert txn.transaction_type == "income"
        assert Decimal(str(txn.amount)) == Decimal("105.00")
        assert Decimal(str(txn.tax_amount)) == Decimal("5.00")

    assert ("new_order",) in [(event,) for event, _payload, _kwargs in socket_emit_spy]
    assert (
        "order_status_updated",
    ) in [(event,) for event, _payload, _kwargs in socket_emit_spy]
    stock_rooms = [
        kwargs.get("room")
        for event, _payload, kwargs in socket_emit_spy
        if event == "stock_updated"
    ]
    assert "admin" in stock_rooms
    assert "customer" in stock_rooms


def test_pos_payment_rejects_short_amount_and_keeps_receipt_locked(
    admin_client,
    product_factory,
):
    _product, variant = product_factory(
        name="Short Pay POS Tart",
        price=Decimal("75"),
        variant_stock=2,
    )
    db.session.commit()
    sign_in(admin_client, "admin@bakery.com", "Admin@bakery")

    create_response = admin_client.post(
        "/admin/pos",
        data={
            "cart_items": json.dumps([{"variant_id": variant.id, "quantity": 1}]),
            f"expected_version_{variant.id}": str(variant.version),
            "payment_mode": "CARD",
            "sale_status": "DELIVERED",
        },
        follow_redirects=False,
    )
    assert create_response.status_code == 302
    with admin_client.application.app_context():
        order = Order.query.filter_by(channel="counter").order_by(Order.id.desc()).first()
        order_id = order.id

    short_payment = admin_client.post(
        f"/admin/pos/orders/{order_id}/payment",
        data={
            "amount_received": "40",
            "payment_method": "CARD",
            "final_status": "DELIVERED",
        },
        follow_redirects=True,
    )

    assert short_payment.status_code == 200
    assert b"Amount received is less than the bill total" in short_payment.data
    with admin_client.application.app_context():
        order = db.session.get(Order, order_id)
        assert order.payment_status == "PENDING"
        assert order.payment.status == "PENDING"
        assert FinancialTransaction.query.filter_by(reference_order_id=order.id).first() is None

    receipt_response = admin_client.get(
        f"/admin/pos/orders/{order_id}/receipt",
        follow_redirects=False,
    )
    assert receipt_response.status_code == 302
    assert receipt_response.headers["Location"].endswith("/payment")


def test_manager_only_voids_pending_pos_bill_and_restores_stock(
    admin_client,
    raw_material_factory,
    product_factory,
    socket_emit_spy,
):
    flour = raw_material_factory(name="Void POS Flour", stock=Decimal("4"))
    product, variant = product_factory(
        name="Void POS Cookie",
        price=Decimal("60"),
        variant_stock=2,
        recipe=[(flour, Decimal("1"))],
    )
    staff_user = User(
        name="Counter Staff",
        email="counter.staff@test.com",
        role="cashier",
        admin_tier="staff",
        is_active=True,
    )
    staff_user.set_password("StaffPass1")
    db.session.add(staff_user)
    db.session.commit()
    sign_in(admin_client, "admin@bakery.com", "Admin@bakery")

    create_response = admin_client.post(
        "/admin/pos",
        data={
            "cart_items": json.dumps([{"variant_id": variant.id, "quantity": 1}]),
            f"expected_version_{variant.id}": str(variant.version),
            "payment_mode": "CASH",
            "sale_status": "DELIVERED",
        },
        follow_redirects=False,
    )
    assert create_response.status_code == 302
    with admin_client.application.app_context():
        order = Order.query.filter_by(channel="counter").order_by(Order.id.desc()).first()
        order_id = order.id
        assert db.session.get(ProductVariant, variant.id).stock == 1
        assert Decimal(str(db.session.get(RawMaterial, flour.id).stock)) == Decimal("3.00")

    admin_client.get("/auth/logout")
    sign_in(admin_client, "counter.staff@test.com", "StaffPass1")
    staff_void_response = admin_client.post(
        f"/admin/pos/orders/{order_id}/void",
        data={"reason": "Staff should not void bills"},
    )
    assert staff_void_response.status_code == 403

    admin_client.get("/auth/logout")
    sign_in(admin_client, "admin@bakery.com", "Admin@bakery")
    admin_void_response = admin_client.post(
        f"/admin/pos/orders/{order_id}/void",
        data={"reason": "Customer cancelled before payment"},
        follow_redirects=True,
    )

    assert admin_void_response.status_code == 200
    assert b"was voided" in admin_void_response.data
    with admin_client.application.app_context():
        order = db.session.get(Order, order_id)
        assert order.status == "CANCELLED"
        assert order.payment_status == "CANCELLED"
        assert order.payment.status == "CANCELLED"
        assert db.session.get(ProductVariant, variant.id).stock == 2
        assert Decimal(str(db.session.get(RawMaterial, flour.id).stock)) == Decimal("4.00")
        assert FinancialTransaction.query.filter_by(reference_order_id=order.id).first() is None

    assert (
        "order_cancelled",
    ) in [(event,) for event, _payload, _kwargs in socket_emit_spy]


def test_walkin_orders_display_allows_kitchen_availability_updates(
    admin_client,
    product_factory,
    socket_emit_spy,
):
    product, variant = product_factory(
        name="Walk-in Display Bun",
        price=Decimal("45"),
        variant_stock=4,
    )
    product.preparation = "Warm before serving"
    kitchen_user = User(
        name="Kitchen Display Staff",
        email="walkin-kitchen@test.com",
        role="kitchen_staff",
        is_active=True,
    )
    kitchen_user.set_password("KitchenPass1")
    db.session.add(kitchen_user)
    db.session.commit()
    variant_id = variant.id
    expected_version = variant.version

    login_response = sign_in(admin_client, "walkin-kitchen@test.com", "KitchenPass1")
    assert login_response.status_code == 302

    response = admin_client.get("/admin/walk-in-orders")

    assert response.status_code == 200
    assert b"Walk-in Orders" in response.data
    assert b"Kitchen team enabled" in response.data
    assert b"Walk-in Display Bun" in response.data
    assert b"Only 4 left" in response.data
    assert b"Update availability / details" in response.data
    assert b"Warm before serving" in response.data

    update_response = admin_client.post(
        f"/admin/pos/variants/{variant_id}/availability",
        data={
            "stock": "0",
            "expected_version": str(expected_version),
            "preparation": "Sold out until 4 PM",
        },
        follow_redirects=True,
    )

    assert update_response.status_code == 200
    assert b"Walk-in product availability updated." in update_response.data
    assert b"Out of Stock" in update_response.data
    assert b"Sold out until 4 PM" in update_response.data
    with admin_client.application.app_context():
        reloaded_variant = db.session.get(ProductVariant, variant_id)
        assert reloaded_variant.stock == 0
        assert reloaded_variant.version == expected_version + 1
        assert reloaded_variant.product.preparation == "Sold out until 4 PM"

    stock_events = [
        payload
        for event, payload, _kwargs in socket_emit_spy
        if event == "stock_updated" and payload.get("variant_id") == variant_id
    ]
    assert stock_events
    assert stock_events[-1]["new_stock"] == 0


def test_counter_sale_competes_with_online_sale_for_same_stock(
    admin_client,
    raw_material_factory,
    product_factory,
):
    flour = raw_material_factory(name="Shared POS Flour", stock=Decimal("2"))
    product, variant = product_factory(
        name="Shared Stock Cake",
        price=Decimal("80"),
        variant_stock=1,
        recipe=[(flour, Decimal("1"))],
    )
    customer = User.query.filter_by(email="customer@test.com").first()
    order_service = admin_client.application.extensions[
        "service_container"
    ].order_service
    line = order_service.build_line_from_variant(variant, 1)

    with db.session.begin_nested():
        order_service.create_order(
            user_id=customer.id,
            lines=[line],
            subtotal=Decimal("80"),
            total=Decimal("80"),
            payment_method="COD",
            payment_status="PENDING",
            status="PLACED",
            channel="online",
            source="WEB",
            fulfillment_type="DELIVERY",
            address_line1="1 Test Lane",
            city="Coimbatore",
            pincode="641002",
            phone="9999999999",
            delivery_slot="09:00 - 11:00",
            delivery_date=utcnow().date(),
        )
    db.session.commit()

    sign_in(admin_client, "admin@bakery.com", "Admin@bakery")
    response = admin_client.post(
        "/admin/pos",
        data={
            "cart_items": json.dumps([{"variant_id": variant.id, "quantity": 1}]),
            "payment_mode": "CASH",
            "sale_status": "DELIVERED",
        },
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert b"out of stock" in response.data
    with admin_client.application.app_context():
        reloaded_variant = db.session.get(ProductVariant, variant.id)
        reloaded_flour = db.session.get(RawMaterial, flour.id)
        assert reloaded_variant.stock == 0
        assert Decimal(str(reloaded_flour.stock)) == Decimal("1.00")
        assert Order.query.filter_by(channel="counter").count() == 0


def test_shared_order_service_records_channel_for_counter_sales(
    db_session,
    raw_material_factory,
    product_factory,
):
    flour = raw_material_factory(name="Service POS Flour", stock=Decimal("4"))
    product, variant = product_factory(
        name="Service POS Bun",
        price=Decimal("25"),
        variant_stock=4,
        recipe=[(flour, Decimal("0.5"))],
    )
    customer = User.query.filter_by(email="customer@test.com").first()
    from bootstrap import get_container

    order_service = get_container().order_service
    line = order_service.build_line_from_variant(variant, 3)
    creation = order_service.create_order(
        user_id=customer.id,
        lines=[line],
        subtotal=Decimal("75"),
        total=Decimal("75"),
        payment_method="CARD",
        payment_status="PAID",
        status="DELIVERED",
        channel="counter",
        source="POS",
        fulfillment_type="PICKUP",
        delivery_slot="Walk-in",
        delivery_date=utcnow().date(),
    )
    db_session.commit()

    order = db.session.get(Order, creation.order.id)
    assert order.channel == "counter"
    assert order.source == "POS"
    assert order.payment_status == "PAID"
    assert db.session.get(ProductVariant, variant.id).stock == 1
    assert Decimal(str(db.session.get(RawMaterial, flour.id).stock)) == Decimal("2.50")

    txn = FinancialTransaction.query.filter_by(reference_order_id=order.id).first()
    assert txn is not None
    assert Decimal(str(txn.amount)) == Decimal("75.00")
