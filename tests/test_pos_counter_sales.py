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
    assert create_order_calls
    assert create_order_calls[0]["channel"] == "counter"
    receipt_response = admin_client.get(response.headers["Location"])
    assert receipt_response.status_code == 200
    assert receipt_response.mimetype in {"application/pdf", "text/html"}
    if receipt_response.mimetype == "text/html":
        assert b"SweetCrumbs Receipt" in receipt_response.data
    with admin_client.application.app_context():
        order = (
            Order.query.filter_by(channel="counter").order_by(Order.id.desc()).first()
        )
        assert order is not None
        assert order.source == "POS"
        assert order.status == "DELIVERED"
        assert order.payment_status == "PAID"
        assert order.fulfillment_type == "PICKUP"
        assert Decimal(str(order.total)) == Decimal("100.00")
        assert order.items.count() == 1

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
        assert Decimal(str(txn.amount)) == Decimal("100.00")

    assert ("new_order",) in [(event,) for event, _payload, _kwargs in socket_emit_spy]
    stock_rooms = [
        kwargs.get("room")
        for event, _payload, kwargs in socket_emit_spy
        if event == "stock_updated"
    ]
    assert "admin" in stock_rooms
    assert "customer" in stock_rooms


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
