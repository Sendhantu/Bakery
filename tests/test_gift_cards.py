from decimal import Decimal

import pytest

from clock import utcnow
from exceptions import ValidationError
from models import FinancialCategory, FinancialTransaction, GiftCard
from services.analytics_service import total_revenue
from services.finance_service import FinanceService


def sign_in(test_client, email, password):
    return test_client.post(
        "/auth/login",
        data={"email": email, "password": password},
        follow_redirects=False,
    )


def create_paid_delivered_order(
    *,
    order_service,
    customer,
    variant,
    subtotal,
    total,
    gift_card_amount=Decimal("0"),
    gift_card_code=None,
):
    line = order_service.build_line_from_variant(variant, 1, unit_price=subtotal)
    return order_service.create_order(
        user_id=customer.id,
        lines=[line],
        subtotal=subtotal,
        total=total,
        gift_card_redemption_amount=gift_card_amount,
        gift_card_code=gift_card_code,
        payment_method="GIFT_CARD" if total == 0 else "CASH",
        payment_status="PAID",
        status="DELIVERED",
        channel="counter",
        source="POS",
        fulfillment_type="PICKUP",
        delivery_slot="Walk-in",
        delivery_date=utcnow().date(),
    ).order


def test_gift_card_purchase_records_liability_not_revenue(
    db_session,
):
    from bootstrap import get_container

    service = get_container().gift_card_service
    finance = FinanceService()
    finance.ensure_default_categories()
    card = service.issue(amount=Decimal("500"), recipient_email="gift@example.com")
    db_session.commit()

    liability_category = FinancialCategory.query.filter_by(
        code="gift_card_liability"
    ).first()
    txn = FinancialTransaction.query.filter_by(
        category_id=liability_category.id,
        idempotency_key=f"gift-card-issued-{card.id}",
    ).first()
    assert txn is not None
    assert txn.transaction_type == "liability"
    assert Decimal(str(txn.amount)) == Decimal("500.00")

    today = utcnow().date()
    assert total_revenue("custom", start_date=today, end_date=today) == Decimal("0")
    pnl = finance.profit_and_loss(start_date=today, end_date=today)
    assert pnl["sales_revenue"] == Decimal("0.00")
    assert pnl["income"] == Decimal("0.00")


def test_partial_redemption_keeps_balance_and_recognizes_redeemed_revenue(
    db_session,
    product_factory,
):
    from bootstrap import get_container

    customer = get_container().user_repository.get_by_email("customer@test.com")
    _product, variant = product_factory(price=Decimal("70"), variant_stock=3)
    card = get_container().gift_card_service.issue(amount=Decimal("100"))
    db_session.flush()

    order = create_paid_delivered_order(
        order_service=get_container().order_service,
        customer=customer,
        variant=variant,
        subtotal=Decimal("70"),
        total=Decimal("0"),
        gift_card_amount=Decimal("70"),
        gift_card_code=card.code,
    )
    get_container().gift_card_service.redeem(card.code, order, Decimal("70"))
    order.placed_at = utcnow()
    db_session.commit()

    reloaded_card = db_session.get(GiftCard, card.id)
    assert Decimal(str(reloaded_card.current_balance)) == Decimal("30.00")
    assert reloaded_card.status == "active"
    redemption_txn = reloaded_card.transactions.filter_by(
        transaction_type="redeemed"
    ).one()
    assert Decimal(str(redemption_txn.amount_change)) == Decimal("-70.00")

    sale_txn = FinancialTransaction.query.filter_by(reference_order_id=order.id).one()
    assert sale_txn.transaction_type == "income"
    assert Decimal(str(sale_txn.amount)) == Decimal("70.00")
    today = utcnow().date()
    assert total_revenue("custom", start_date=today, end_date=today) == Decimal("70.00")


def test_coupon_loyalty_then_gift_card_final_charge_order(
    db_session,
    product_factory,
):
    from bootstrap import get_container

    customer = get_container().user_repository.get_by_email("customer@test.com")
    _product, variant = product_factory(price=Decimal("100"), variant_stock=3)
    card = get_container().gift_card_service.issue(amount=Decimal("50"))
    db_session.flush()

    subtotal = Decimal("100")
    coupon_discount = Decimal("10")
    loyalty_discount = Decimal("10")
    payable_before_gift_card = subtotal - coupon_discount - loyalty_discount
    gift_card_preview = get_container().gift_card_service.preview_redemption(
        card.code,
        payable_before_gift_card,
    )
    final_total = payable_before_gift_card - gift_card_preview["amount"]

    order = create_paid_delivered_order(
        order_service=get_container().order_service,
        customer=customer,
        variant=variant,
        subtotal=subtotal,
        total=final_total,
        gift_card_amount=gift_card_preview["amount"],
        gift_card_code=card.code,
    )
    order.discount = coupon_discount
    order.loyalty_discount = loyalty_discount
    get_container().gift_card_service.redeem(
        card.code,
        order,
        payable_before_gift_card,
    )
    db_session.commit()

    assert Decimal(str(order.discount)) == Decimal("10.00")
    assert Decimal(str(order.loyalty_discount)) == Decimal("10.00")
    assert Decimal(str(order.gift_card_redemption_amount)) == Decimal("50.00")
    assert Decimal(str(order.total)) == Decimal("30.00")
    sale_txn = FinancialTransaction.query.filter_by(reference_order_id=order.id).one()
    assert Decimal(str(sale_txn.amount)) == Decimal("80.00")


def test_over_redemption_never_drives_balance_below_zero(
    db_session,
    product_factory,
):
    from bootstrap import get_container

    customer = get_container().user_repository.get_by_email("customer@test.com")
    _product, variant = product_factory(price=Decimal("30"), variant_stock=3)
    card = get_container().gift_card_service.issue(amount=Decimal("50"))
    db_session.flush()

    order = create_paid_delivered_order(
        order_service=get_container().order_service,
        customer=customer,
        variant=variant,
        subtotal=Decimal("30"),
        total=Decimal("0"),
        gift_card_amount=Decimal("30"),
        gift_card_code=card.code,
    )
    get_container().gift_card_service.redeem(card.code, order, Decimal("30"))
    db_session.flush()

    assert Decimal(str(card.current_balance)) == Decimal("20.00")
    with pytest.raises(ValidationError):
        get_container().gift_card_service.manual_adjust(
            card,
            Decimal("-25"),
            reason="attempted over redemption",
        )
    assert Decimal(str(card.current_balance)) == Decimal("20.00")


def test_admin_gift_cards_page_and_pos_issue_route_are_manager_gated(admin_client):
    sign_in(admin_client, "admin@bakery.com", "Admin@bakery")
    response = admin_client.get("/admin/gift-cards")
    assert response.status_code == 200
    assert b"Outstanding Liability" in response.data
    assert b"Available Amount" in response.data
    assert b'data-toggle-target="#issue-gift-card-form"' in response.data
    assert b'id="issue-gift-card-form" class="card mb-4 hidden"' in response.data

    response = admin_client.post(
        "/admin/pos/gift-card",
        data={"amount": "250", "recipient_email": "counter@example.com"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"issued" in response.data
    assert b"Available Amount" in response.data


def test_customer_gift_cards_show_owned_available_amounts(client):
    sign_in(client, "customer@test.com", "customer123")

    with client.application.app_context():
        from models import User, db
        from bootstrap import get_container

        customer = User.query.filter_by(email="customer@test.com").first()
        assert customer is not None
        purchased_card = get_container().gift_card_service.issue(
            amount=Decimal("200"),
            purchased_by_user_id=customer.id,
            recipient_email="friend@example.com",
        )
        received_card = get_container().gift_card_service.issue(
            amount=Decimal("150"),
            recipient_email="CUSTOMER@Test.com",
        )
        other_card = get_container().gift_card_service.issue(
            amount=Decimal("999"),
            recipient_email="other@example.com",
        )
        db.session.commit()
        purchased_code = purchased_card.code
        received_code = received_card.code
        other_code = other_card.code

    response = client.get("/gift-cards")

    assert response.status_code == 200
    assert b"Available Gift Card Amount" in response.data
    assert b"Available Amount" in response.data
    assert purchased_code.encode() in response.data
    assert received_code.encode() in response.data
    assert other_code.encode() not in response.data
    assert b"350.00" in response.data
