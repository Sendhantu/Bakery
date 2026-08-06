from datetime import date, datetime, time
from decimal import Decimal
import json

import pytest

from bootstrap import get_container
from clock import utcnow
from exceptions import ValidationError
from models import (
    FinancialTransaction,
    GiftCard,
    LoyaltyLedger,
    Notification,
    Order,
    ProductVariant,
    PurchaseOrder,
    PurchaseOrderItem,
    RawMaterial,
    RecurringSubscription,
    Refund,
    SubscriptionItem,
    SubscriptionOrderLog,
    User,
    Vendor,
    db,
)
from services.analytics_service import total_revenue


SCENARIO_DAY = date(2026, 7, 28)
SCENARIO_MOMENT = datetime.combine(SCENARIO_DAY, time(10, 0))


def sign_in(test_client, email, password):
    return test_client.post(
        "/auth/login",
        data={"email": email, "password": password},
        follow_redirects=False,
    )


def create_admin_user(email, tier, password="AdminTier1"):
    user = User(
        name=f"{tier.title()} Scenario User",
        email=email,
        role="admin",
        admin_tier=tier,
        is_active=True,
    )
    user.set_password(password)
    db.session.add(user)
    db.session.flush()
    return user


def create_order(
    customer,
    variant,
    *,
    quantity=1,
    unit_price=Decimal("100"),
    subtotal=None,
    total=None,
    discount=Decimal("0"),
    loyalty_discount=Decimal("0"),
    gift_card_redemption_amount=Decimal("0"),
    gift_card_code=None,
    status="DELIVERED",
    payment_status="PAID",
    channel="online",
    source="WEB",
):
    order_service = get_container().order_service
    line = order_service.build_line_from_variant(
        variant,
        quantity,
        unit_price=unit_price,
    )
    subtotal = Decimal(str(subtotal if subtotal is not None else unit_price * quantity))
    total = Decimal(
        str(total if total is not None else subtotal - discount - loyalty_discount)
    )
    creation = order_service.create_order(
        user_id=customer.id,
        lines=[line],
        subtotal=subtotal,
        discount=discount,
        loyalty_discount=loyalty_discount,
        total=total,
        gift_card_redemption_amount=gift_card_redemption_amount,
        gift_card_code=gift_card_code,
        payment_method="GIFT_CARD" if total == 0 else "CASH",
        payment_status=payment_status,
        status=status,
        channel=channel,
        source=source,
        fulfillment_type="PICKUP",
        delivery_slot="Scenario",
        delivery_date=SCENARIO_DAY,
        payment_reason="scenario_test",
    )
    creation.order.placed_at = SCENARIO_MOMENT
    for txn in FinancialTransaction.query.filter_by(
        reference_order_id=creation.order.id
    ).all():
        txn.created_at = SCENARIO_MOMENT
    return creation.order


def create_subscription(user, variant, *, quantity=1, next_date=SCENARIO_DAY):
    subscription = RecurringSubscription(
        user_id=user.id,
        status="active",
        frequency="weekly",
        next_scheduled_date=next_date,
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


def create_purchase_order(material, *, gstin, gst_rate=Decimal("18")):
    vendor = Vendor(
        name=f"Scenario Vendor {material.name}",
        contact_person="Scenario Buyer",
        phone="9999990000",
        gstin=gstin,
        is_active=True,
    )
    db.session.add(vendor)
    db.session.flush()
    po = PurchaseOrder(
        vendor_id=vendor.id,
        status="ordered",
        order_date=SCENARIO_DAY,
        expected_delivery_date=SCENARIO_DAY,
        gst_rate_percent=gst_rate,
    )
    db.session.add(po)
    db.session.flush()
    db.session.add(
        PurchaseOrderItem(
            purchase_order_id=po.id,
            raw_material_id=material.id,
            quantity=Decimal("5"),
            unit_cost=Decimal("40"),
        )
    )
    db.session.flush()
    return vendor, po


def ledger_income_expense_net(start_date=SCENARIO_DAY, end_date=SCENARIO_DAY):
    selected = get_container().finance_service.resolve_period_range(
        "custom",
        start_date=start_date,
        end_date=end_date,
    )
    start = selected["start"]
    end = selected["end"]
    total = Decimal("0")
    for txn in FinancialTransaction.query.filter(
        FinancialTransaction.created_at >= start,
        FinancialTransaction.created_at < end,
        FinancialTransaction.transaction_type.in_(("income", "expense")),
    ).all():
        amount = Decimal(str(txn.amount or 0))
        total += amount if txn.transaction_type == "income" else -amount
    return total.quantize(Decimal("0.01"))


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Partial refund amount and partial stock reversal are not modeled by "
        "OrderReversalService.cancel_or_refund_order yet."
    ),
)
def test_online_order_coupon_loyalty_partial_refund_keeps_money_stock_and_tax_correct(
    db_session,
    raw_material_factory,
    product_factory,
):
    flour = raw_material_factory(name="Scenario Refund Flour", stock=Decimal("10"))
    _product, variant = product_factory(
        name="Scenario Refund Cake",
        price=Decimal("100"),
        variant_stock=5,
        recipe=[(flour, Decimal("1"))],
    )
    customer = User.query.filter_by(email="customer@test.com").first()
    db.session.add(LoyaltyLedger(user_id=customer.id, points=300, reason="seed"))
    db.session.flush()

    order = create_order(
        customer,
        variant,
        quantity=2,
        unit_price=Decimal("100"),
        subtotal=Decimal("200"),
        discount=Decimal("20"),
        loyalty_discount=Decimal("10"),
        total=Decimal("170"),
        status="PREPARING",
    )
    get_container().loyalty_service.redeem_for_order(
        customer.id,
        order.id,
        100,
        Decimal("200"),
    )
    db.session.commit()

    before_points = customer.loyalty_points
    get_container().order_reversal_service.cancel_or_refund_order(
        order,
        reason="Partial damaged item",
        actor_id=None,
        reverse_stock=True,
        allow_paid_refund=True,
    )
    db.session.commit()

    refund = Refund.query.filter_by(order_id=order.id).one()
    refund_txn = FinancialTransaction.query.filter_by(
        reference_order_id=order.id,
        transaction_type="expense",
    ).one()
    assert Decimal(str(refund.amount)) == Decimal("50.00")
    assert Decimal(str(refund_txn.amount)) == Decimal("50.00")
    assert db.session.get(ProductVariant, variant.id).stock == 4
    assert Decimal(str(db.session.get(RawMaterial, flour.id).stock)) == Decimal("9.00")
    assert customer.loyalty_points == before_points
    gst = get_container().finance_service.gst_summary(
        start_date=SCENARIO_DAY,
        end_date=SCENARIO_DAY,
    )
    assert gst["net_gst_liability"] == Decimal("5.72")


def test_counter_sale_and_online_order_compete_for_last_stock_unit(
    db_session,
    raw_material_factory,
    product_factory,
):
    flour = raw_material_factory(name="Scenario Last Unit Flour", stock=Decimal("3"))
    _product, variant = product_factory(
        name="Scenario Last Unit Tart",
        price=Decimal("80"),
        variant_stock=1,
        recipe=[(flour, Decimal("1"))],
    )
    customer = User.query.filter_by(email="customer@test.com").first()

    online_order = create_order(
        customer,
        variant,
        quantity=1,
        unit_price=Decimal("80"),
        total=Decimal("80"),
        status="PLACED",
        payment_status="PENDING",
    )
    db_session.commit()

    with pytest.raises(ValidationError):
        create_order(
            customer,
            variant,
            quantity=1,
            unit_price=Decimal("80"),
            total=Decimal("80"),
            channel="counter",
            source="POS",
        )
    db_session.rollback()

    assert online_order.id is not None
    reloaded_variant = db.session.get(ProductVariant, variant.id)
    assert reloaded_variant.stock == 0
    assert reloaded_variant.stock >= 0
    assert (
        Order.query.filter(Order.items.any(product_id=variant.product_id)).count() == 1
    )


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Gift-card refund restoration is not defined; current refund logic refunds "
        "only order.total and does not restore redeemed gift-card balance."
    ),
)
def test_gift_card_purchase_partial_redemption_then_refund_nets_revenue_and_balance(
    db_session,
    raw_material_factory,
    product_factory,
):
    flour = raw_material_factory(name="Scenario Gift Refund Flour", stock=Decimal("5"))
    _product, variant = product_factory(
        name="Scenario Gift Refund Cake",
        price=Decimal("120"),
        variant_stock=3,
        recipe=[(flour, Decimal("1"))],
    )
    customer = User.query.filter_by(email="customer@test.com").first()
    gift_service = get_container().gift_card_service
    card = gift_service.issue(amount=Decimal("50"), purchased_by_user_id=customer.id)
    db_session.commit()

    assert total_revenue(
        "custom", start_date=SCENARIO_DAY, end_date=SCENARIO_DAY
    ) == Decimal("0")

    order = create_order(
        customer,
        variant,
        subtotal=Decimal("120"),
        unit_price=Decimal("120"),
        total=Decimal("70"),
        gift_card_redemption_amount=Decimal("50"),
        gift_card_code=card.code,
        status="PREPARING",
    )
    gift_service.redeem(card.code, order, Decimal("120"), actor_id=customer.id)
    db_session.commit()

    sale_txn = FinancialTransaction.query.filter_by(
        reference_order_id=order.id,
        transaction_type="income",
    ).one()
    assert Decimal(str(sale_txn.amount)) == Decimal("120.00")
    assert Decimal(str(card.current_balance)) == Decimal("0.00")

    get_container().order_reversal_service.cancel_or_refund_order(
        order,
        reason="Refund gift-card paid order",
        actor_id=None,
        reverse_stock=True,
        allow_paid_refund=True,
    )
    db_session.commit()

    restored_card = db.session.get(GiftCard, card.id)
    refund_txn = FinancialTransaction.query.filter_by(
        reference_order_id=order.id,
        transaction_type="expense",
    ).one()
    assert Decimal(str(restored_card.current_balance)) == Decimal("50.00")
    assert Decimal(str(refund_txn.amount)) == Decimal("120.00")
    assert ledger_income_expense_net() == Decimal("0.00")


def test_subscription_generation_insufficient_stock_logs_failure_without_partial_rows(
    db_session,
    raw_material_factory,
    product_factory,
):
    flour = raw_material_factory(name="Scenario Empty Subscription Flour", stock=0)
    _product, variant = product_factory(
        name="Scenario Subscription Loaf",
        price=Decimal("90"),
        variant_stock=2,
        recipe=[(flour, Decimal("1"))],
    )
    customer = User.query.filter_by(email="customer@test.com").first()
    subscription = create_subscription(customer, variant, quantity=1)
    order_count = Order.query.count()
    txn_count = FinancialTransaction.query.count()
    notification_count = Notification.query.count()
    db_session.commit()

    summary = get_container().subscription_service.create_due_orders(today=SCENARIO_DAY)

    assert summary == {"success": 0, "failed": 1, "order_ids": [], "log_ids": []}
    log = SubscriptionOrderLog.query.filter_by(subscription_id=subscription.id).one()
    assert log.order_id is None
    assert log.status == "failed_insufficient_stock"
    assert "Insufficient stock" in log.notes
    assert Order.query.count() == order_count
    assert FinancialTransaction.query.count() == txn_count
    assert Notification.query.count() > notification_count
    assert db.session.get(
        RecurringSubscription, subscription.id
    ).next_scheduled_date == date(2026, 8, 4)


def test_vendor_po_received_expense_and_gst_input_credit_registered_vs_unregistered(
    db_session,
    raw_material_factory,
):
    finance = get_container().finance_service
    registered_material = raw_material_factory(name="Scenario GST Butter", stock=0)
    unregistered_material = raw_material_factory(name="Scenario NonGST Butter", stock=0)
    registered_vendor, registered_po = create_purchase_order(
        registered_material,
        gstin="29ABCDE1234F1Z5",
        gst_rate=Decimal("18"),
    )
    unregistered_vendor, unregistered_po = create_purchase_order(
        unregistered_material,
        gstin=None,
        gst_rate=Decimal("18"),
    )

    registered_result = get_container().purchase_order_service.receive_purchase_order(
        registered_po,
        actor_id=None,
    )
    unregistered_result = get_container().purchase_order_service.receive_purchase_order(
        unregistered_po,
        actor_id=None,
    )
    registered_result["transaction"].created_at = SCENARIO_MOMENT
    unregistered_result["transaction"].created_at = SCENARIO_MOMENT
    db_session.commit()

    assert registered_material.stock == Decimal("5.00")
    assert unregistered_material.stock == Decimal("5.00")
    assert registered_vendor.input_tax_credit_eligible is True
    assert unregistered_vendor.input_tax_credit_eligible is False
    assert registered_result["transaction"].vendor_id == registered_vendor.id
    assert unregistered_result["transaction"].vendor_id == unregistered_vendor.id
    assert registered_result["transaction"].amount == Decimal("200.00")
    assert unregistered_result["transaction"].amount == Decimal("200.00")
    assert registered_result["transaction"].tax_amount == Decimal("36.00")
    assert unregistered_result["transaction"].tax_amount == Decimal("0.00")

    gst = finance.gst_summary(start_date=SCENARIO_DAY, end_date=SCENARIO_DAY)
    assert gst["input_gst_recorded"] == Decimal("36.00")
    assert gst["non_creditable_input_gst"] == Decimal("36.00")
    assert gst["gst_paid"] == Decimal("0.00")


def test_staff_counter_sale_session_cannot_access_refund_vendor_or_finance(
    admin_client,
    raw_material_factory,
    product_factory,
):
    flour = raw_material_factory(name="Scenario Staff Flour", stock=Decimal("5"))
    _product, variant = product_factory(
        name="Scenario Staff Bun",
        price=Decimal("40"),
        variant_stock=2,
        recipe=[(flour, Decimal("1"))],
    )
    staff = create_admin_user("scenario.staff@bakery.com", "staff")
    db.session.commit()

    sign_in(admin_client, "scenario.staff@bakery.com", "AdminTier1")
    sale_response = admin_client.post(
        "/admin/pos",
        data={
            "cart_items": json.dumps([{"variant_id": variant.id, "quantity": 1}]),
            f"expected_version_{variant.id}": str(variant.version),
            "payment_mode": "CASH",
            "sale_status": "DELIVERED",
            "customer_name": "Scenario Counter Guest",
        },
        follow_redirects=False,
    )
    assert sale_response.status_code == 302

    with admin_client.application.app_context():
        order = (
            Order.query.filter_by(channel="counter").order_by(Order.id.desc()).first()
        )
        assert order is not None
        order_id = order.id

    refund_response = admin_client.post(
        f"/admin/orders/{order_id}/cancel-refund",
        data={
            "action": "refund",
            "reason": "Staff should be blocked",
            "stock_handling": "reverse",
            "confirm_reversal": "yes",
        },
    )
    finance_response = admin_client.get("/admin/finance")
    vendor_create_response = admin_client.post(
        "/admin/vendors/add",
        data={"name": "Staff Blocked Vendor"},
    )
    po_create_response = admin_client.get("/admin/purchase-orders/new")

    assert staff.admin_tier == "staff"
    assert refund_response.status_code == 403
    assert finance_response.status_code == 403
    assert vendor_create_response.status_code == 403
    assert po_create_response.status_code == 403


def test_full_period_reconciliation_matches_analytics_ledger_and_finance_dashboard(
    db_session,
    raw_material_factory,
    product_factory,
):
    finance = get_container().finance_service
    customer = User.query.filter_by(email="customer@test.com").first()
    flour = raw_material_factory(name="Scenario Reconcile Flour", stock=Decimal("20"))
    _product, variant = product_factory(
        name="Scenario Reconcile Cake",
        price=Decimal("100"),
        variant_stock=10,
        recipe=[(flour, Decimal("0.5"))],
    )

    create_order(customer, variant, unit_price=Decimal("100"), total=Decimal("100"))
    create_order(
        customer,
        variant,
        unit_price=Decimal("50"),
        total=Decimal("50"),
        channel="counter",
        source="POS",
    )
    card = get_container().gift_card_service.issue(
        amount=Decimal("100"),
        purchased_by_user_id=customer.id,
    )
    db_session.flush()
    gift_order = create_order(
        customer,
        variant,
        unit_price=Decimal("70"),
        subtotal=Decimal("70"),
        total=Decimal("30"),
        gift_card_redemption_amount=Decimal("40"),
        gift_card_code=card.code,
    )
    get_container().gift_card_service.redeem(card.code, gift_order, Decimal("70"))

    refunded_order = create_order(
        customer,
        variant,
        unit_price=Decimal("60"),
        total=Decimal("60"),
        status="PREPARING",
    )
    get_container().order_reversal_service.cancel_or_refund_order(
        refunded_order,
        reason="Scenario full-period refund",
        actor_id=None,
        reverse_stock=True,
        allow_paid_refund=True,
    )

    subscription = create_subscription(customer, variant, quantity=1)
    get_container().subscription_service.generate_order_for_subscription(
        subscription,
        today=SCENARIO_DAY,
    )
    FinancialTransaction.query.update(
        {FinancialTransaction.created_at: SCENARIO_MOMENT},
        synchronize_session=False,
    )
    Order.query.update({Order.placed_at: SCENARIO_MOMENT}, synchronize_session=False)
    db_session.commit()

    analytics_revenue = Decimal(
        str(total_revenue("custom", start_date=SCENARIO_DAY, end_date=SCENARIO_DAY))
    ).quantize(Decimal("0.01"))
    ledger_net = ledger_income_expense_net()
    dashboard = finance.dashboard_payload(
        "custom",
        start_date=SCENARIO_DAY,
        end_date=SCENARIO_DAY,
    )

    assert analytics_revenue == Decimal("220.00")
    assert ledger_net == Decimal("220.00")
    assert dashboard["pnl"]["sales_revenue"] == Decimal("220.00")
    assert analytics_revenue == ledger_net == dashboard["pnl"]["sales_revenue"]
