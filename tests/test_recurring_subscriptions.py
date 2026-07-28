from datetime import date
from decimal import Decimal

from models import (
    FinancialTransaction,
    Notification,
    Order,
    PaymentLink,
    ProductVariant,
    RawMaterial,
    RecurringSubscription,
    StockMovement,
    SubscriptionItem,
    SubscriptionOrderLog,
    User,
    db,
)


def sign_in(test_client, email, password):
    return test_client.post(
        "/auth/login",
        data={"email": email, "password": password},
        follow_redirects=False,
    )


def _create_subscription(
    user, variant, *, quantity=1, frequency="weekly", next_date=None
):
    subscription = RecurringSubscription(
        user_id=user.id,
        status="active",
        frequency=frequency,
        days_of_week="0,3" if frequency == "custom" else None,
        next_scheduled_date=next_date or date(2026, 7, 28),
        payment_method_reference="manual_payment_link",
        delivery_window="Morning",
    )
    db.session.add(subscription)
    db.session.flush()
    db.session.add(
        SubscriptionItem(
            subscription_id=subscription.id,
            product_id=variant.product_id,
            variant_id=variant.id,
            quantity=quantity,
        )
    )
    db.session.flush()
    return subscription


def test_due_subscription_generates_order_through_shared_service(
    db_session,
    raw_material_factory,
    product_factory,
    socket_emit_spy,
    monkeypatch,
):
    flour = raw_material_factory(name="Subscription Flour", stock=Decimal("5"))
    product, variant = product_factory(
        name="Subscription Croissant",
        price=Decimal("60"),
        variant_stock=5,
        recipe=[(flour, Decimal("0.5"))],
    )
    customer = User.query.filter_by(email="customer@test.com").first()
    subscription = _create_subscription(customer, variant, quantity=2)
    db_session.commit()

    from bootstrap import get_container

    order_service = get_container().order_service
    original_create_order = order_service.create_order
    create_order_calls = []

    def spy_create_order(*args, **kwargs):
        create_order_calls.append(kwargs)
        return original_create_order(*args, **kwargs)

    monkeypatch.setattr(order_service, "create_order", spy_create_order)

    summary = get_container().subscription_service.create_due_orders(
        today=date(2026, 7, 28)
    )

    assert summary["success"] == 1
    assert summary["failed"] == 0
    assert create_order_calls
    assert create_order_calls[0]["channel"] == "subscription"
    with db_session.begin_nested():
        order = db.session.get(Order, summary["order_ids"][0])
        assert order.channel == "subscription"
        assert order.source == "SUBSCRIPTION"
        assert order.payment_status == "PENDING"
        assert Decimal(str(order.total)) == Decimal("120.00")
        assert order.items.count() == 1

        refreshed_subscription = db.session.get(RecurringSubscription, subscription.id)
        assert refreshed_subscription.next_scheduled_date == date(2026, 8, 4)
        assert db.session.get(ProductVariant, variant.id).stock == 3
        assert Decimal(str(db.session.get(RawMaterial, flour.id).stock)) == Decimal(
            "4.00"
        )
        assert (
            StockMovement.query.filter_by(
                reference_order_id=order.id,
                reason="order_deduction",
            ).count()
            == 1
        )
        assert PaymentLink.query.filter_by(order_id=order.id).first() is not None
        assert (
            FinancialTransaction.query.filter_by(reference_order_id=order.id).first()
            is None
        )
        assert (
            SubscriptionOrderLog.query.filter_by(
                subscription_id=subscription.id,
                status="success",
            ).count()
            == 1
        )
        assert Notification.query.filter_by(user_id=customer.id).count() >= 1

    assert "new_order" in [event for event, _payload, _kwargs in socket_emit_spy]
    assert "stock_updated" in [event for event, _payload, _kwargs in socket_emit_spy]


def test_subscription_stock_failure_is_logged_and_other_due_subscriptions_continue(
    db_session,
    raw_material_factory,
    product_factory,
):
    bad_material = raw_material_factory(name="Empty Subscription Flour", stock=0)
    bad_product, bad_variant = product_factory(
        name="Impossible Weekly Bread",
        price=Decimal("90"),
        variant_stock=5,
        recipe=[(bad_material, Decimal("1"))],
    )
    good_material = raw_material_factory(name="Available Subscription Flour", stock=5)
    good_product, good_variant = product_factory(
        name="Available Weekly Bread",
        price=Decimal("80"),
        variant_stock=5,
        recipe=[(good_material, Decimal("1"))],
    )
    customer = User.query.filter_by(email="customer@test.com").first()
    bad_subscription = _create_subscription(customer, bad_variant, quantity=1)
    good_subscription = _create_subscription(customer, good_variant, quantity=1)
    db_session.commit()

    from bootstrap import get_container

    summary = get_container().subscription_service.create_due_orders(
        today=date(2026, 7, 28)
    )

    assert summary["success"] == 1
    assert summary["failed"] == 1
    failed_log = SubscriptionOrderLog.query.filter_by(
        subscription_id=bad_subscription.id
    ).first()
    assert failed_log is not None
    assert failed_log.order_id is None
    assert failed_log.status == "failed_insufficient_stock"
    assert "Insufficient stock" in failed_log.notes

    success_log = SubscriptionOrderLog.query.filter_by(
        subscription_id=good_subscription.id,
        status="success",
    ).first()
    assert success_log is not None
    assert success_log.order_id is not None
    assert Order.query.filter_by(channel="subscription").count() == 1
    assert db.session.get(
        RecurringSubscription, bad_subscription.id
    ).next_scheduled_date == date(2026, 8, 4)


def test_subscription_next_scheduled_date_advances_for_custom_days(
    db_session,
    raw_material_factory,
    product_factory,
):
    flour = raw_material_factory(name="Date Flour", stock=5)
    product, variant = product_factory(
        name="Date Bread",
        price=Decimal("30"),
        variant_stock=5,
        recipe=[(flour, Decimal("0.25"))],
    )
    customer = User.query.filter_by(email="customer@test.com").first()
    subscription = _create_subscription(
        customer,
        variant,
        frequency="custom",
        next_date=date(2026, 7, 28),
    )

    from bootstrap import get_container

    service = get_container().subscription_service
    assert service.next_scheduled_date(subscription, date(2026, 7, 28)) == date(
        2026, 7, 30
    )
    assert service.next_scheduled_date(subscription, date(2026, 7, 30)) == date(
        2026, 8, 3
    )


def test_customer_recurring_subscriptions_page_renders(client):
    sign_in(client, "customer@test.com", "customer123")
    response = client.get("/subscriptions")

    assert response.status_code == 200
    assert b"Recurring Orders" in response.data
    assert b"Auto-charge is not enabled yet" in response.data


def test_admin_subscriptions_page_shows_recurring_failures(
    admin_client,
    raw_material_factory,
    product_factory,
):
    flour = raw_material_factory(name="Admin Subscription Flour", stock=0)
    product, variant = product_factory(
        name="Admin Subscription Bread",
        price=Decimal("45"),
        variant_stock=1,
        recipe=[(flour, Decimal("1"))],
    )
    customer = User.query.filter_by(email="customer@test.com").first()
    subscription = _create_subscription(customer, variant)
    db.session.add(
        SubscriptionOrderLog(
            subscription_id=subscription.id,
            status="failed_insufficient_stock",
            notes="Insufficient stock: Admin Subscription Flour",
        )
    )
    db.session.commit()
    sign_in(admin_client, "admin@bakery.com", "Admin@bakery")

    response = admin_client.get("/admin/subscriptions")

    assert response.status_code == 200
    assert b"Recurring Order Subscriptions" in response.data
    assert b"Failed Subscription Cycles" in response.data
    assert b"Insufficient stock" in response.data
