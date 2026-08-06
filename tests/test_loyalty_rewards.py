from datetime import timedelta
from decimal import Decimal

import pytest

from bootstrap import get_container
from clock import utcnow
from models import (
    AuditLog,
    Cart,
    LoyaltyLedger,
    Notification,
    Product,
    ProductVariant,
    User,
    db,
)
from utils.notifications import notify_order_status_change


def sign_in(test_client, email, password):
    return test_client.post(
        "/auth/login",
        data={"email": email, "password": password},
        follow_redirects=False,
    )


def test_paid_delivered_order_earns_points_once(app, db_session, order_factory):
    order = order_factory(
        status="PACKED",
        payment_status="PAID",
        total=Decimal("120"),
    )
    db_session.commit()

    with app.test_request_context("/admin/orders/test"):
        updated = get_container().order_service.update_order_status(
            order.id,
            "DELIVERED",
            actor="admin",
        )

    assert updated.status == "DELIVERED"
    earned = LoyaltyLedger.query.filter_by(
        user_id=order.user_id,
        order_id=order.id,
        reason="order_earned",
    ).all()
    assert len(earned) == 1
    assert earned[0].points == 12

    second_award = get_container().loyalty_service.award_order_points(updated)
    assert second_award == 0
    assert (
        LoyaltyLedger.query.filter_by(
            user_id=order.user_id,
            order_id=order.id,
            reason="order_earned",
        ).count()
        == 1
    )


def test_loyalty_notification_links_to_customer_profile(app, db_session, order_factory):
    order = order_factory(
        status="DELIVERED",
        payment_status="PAID",
        total=Decimal("120"),
    )
    db_session.commit()

    with app.test_request_context("/admin/orders/test"):
        notify_order_status_change(order, "DELIVERED", old_status="OUT_FOR_DELIVERY")

    loyalty_notification = Notification.query.filter_by(
        user_id=order.user_id,
        type="loyalty",
    ).first()
    assert loyalty_notification is not None
    assert loyalty_notification.link == "/auth/profile"


def test_checkout_redemption_reduces_points_and_applies_discount(client):
    sign_in(client, "customer@test.com", "customer123")
    with client.application.app_context():
        customer = User.query.filter_by(email="customer@test.com").first()
        assert customer is not None
        product = Product(
            name="Small Loyalty Tart",
            base_price=100,
            is_active=True,
        )
        db.session.add(product)
        db.session.flush()
        variant = ProductVariant(
            product_id=product.id,
            name="Standard",
            price=100,
            stock=5,
        )
        db.session.add(variant)
        db.session.add(
            LoyaltyLedger(
                user_id=customer.id,
                points=20,
                reason="manual_adjustment",
            )
        )
        db.session.add(
            Cart(
                user_id=customer.id,
                product_id=variant.product_id,
                variant_id=variant.id,
                quantity=1,
            )
        )
        db.session.commit()
        customer_id = customer.id

    tomorrow = (utcnow().date() + timedelta(days=1)).isoformat()
    response = client.post(
        "/checkout",
        data={
            "fulfillment_type": "PICKUP",
            "pickup_date": tomorrow,
            "pickup_slot": "09:00 - 11:00",
            "pickup_phone": "9999999999",
            "payment_method": "COD",
            "loyalty_points": "10",
        },
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert b"placed successfully" in response.data
    with client.application.app_context():
        redeemed = LoyaltyLedger.query.filter_by(
            user_id=customer_id,
            reason="redeemed",
        ).first()
        assert redeemed is not None
        assert redeemed.points == -10
        assert redeemed.order.loyalty_discount == Decimal("10.00")
        assert db.session.get(User, customer_id).loyalty_points == 10


def test_checkout_points_section_shows_available_points_and_redeem_rules(client):
    sign_in(client, "customer@test.com", "customer123")
    with client.application.app_context():
        customer = User.query.filter_by(email="customer@test.com").first()
        product = Product(
            name="Large Loyalty Cake",
            base_price=600,
            is_active=True,
        )
        db.session.add(product)
        db.session.flush()
        variant = ProductVariant(
            product_id=product.id,
            name="Standard",
            price=600,
            stock=5,
        )
        db.session.add(variant)
        db.session.add(
            LoyaltyLedger(
                user_id=customer.id,
                points=120,
                reason="manual_adjustment",
            )
        )
        db.session.add(
            Cart(
                user_id=customer.id,
                product_id=product.id,
                variant_id=variant.id,
                quantity=1,
            )
        )
        db.session.commit()

    response = client.get("/checkout")

    assert response.status_code == 200
    assert b"Available:" in response.data
    assert b"120" in response.data
    assert b"Redeem in 10-point steps" in response.data
    assert b"at least 60 points" in response.data


def test_loyalty_preview_requires_ten_point_steps(client):
    sign_in(client, "customer@test.com", "customer123")
    with client.application.app_context():
        customer = User.query.filter_by(email="customer@test.com").first()
        db.session.add(
            LoyaltyLedger(
                user_id=customer.id,
                points=100,
                reason="manual_adjustment",
            )
        )
        db.session.commit()

    response = client.post(
        "/api/loyalty/validate-redeem",
        json={"points": 15, "subtotal": 400},
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["valid"] is False
    assert "multiples of 10" in payload["message"]


def test_loyalty_preview_requires_minimum_redemption_for_large_orders(client):
    sign_in(client, "customer@test.com", "customer123")
    with client.application.app_context():
        customer = User.query.filter_by(email="customer@test.com").first()
        db.session.add(
            LoyaltyLedger(
                user_id=customer.id,
                points=500,
                reason="manual_adjustment",
            )
        )
        db.session.commit()

    low_response = client.post(
        "/api/loyalty/validate-redeem",
        json={"points": 50, "subtotal": 600},
    )
    valid_response = client.post(
        "/api/loyalty/validate-redeem",
        json={"points": 60, "subtotal": 600},
    )

    low_payload = low_response.get_json()
    valid_payload = valid_response.get_json()
    assert low_payload["valid"] is False
    assert low_payload["min_points_required"] == 60
    assert "at least 60 points" in low_payload["message"]
    assert valid_payload["valid"] is True
    assert valid_payload["points_applied"] == 60
    assert valid_payload["discount"] == 60


def test_loyalty_service_blocks_negative_manual_adjustment(db_session, user_factory):
    user = user_factory(email="negative-loyalty@test.com")
    db_session.add(LoyaltyLedger(user_id=user.id, points=25, reason="seed"))
    db_session.commit()

    with pytest.raises(ValueError, match="negative"):
        get_container().loyalty_service.adjust_points(
            user.id,
            -30,
            "correction",
        )

    assert user.loyalty_points == 25
    assert LoyaltyLedger.query.filter_by(user_id=user.id).count() == 1


def test_admin_manual_adjustment_creates_ledger_and_audit_log(admin_client):
    sign_in(admin_client, "admin@bakery.com", "Admin@bakery")
    with admin_client.application.app_context():
        customer = User.query.filter_by(email="customer@test.com").first()
        assert customer is not None
        customer_id = customer.id

    response = admin_client.post(
        "/admin/loyalty/adjust",
        data={
            "user_id": str(customer_id),
            "points": "75",
            "reason": "goodwill",
        },
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert b"Adjusted +75 pts" in response.data
    with admin_client.application.app_context():
        entry = LoyaltyLedger.query.filter_by(
            user_id=customer_id,
            points=75,
            reason="goodwill",
        ).first()
        assert entry is not None
        audit = AuditLog.query.filter_by(
            entity_type="User",
            entity_id=str(customer_id),
            action="loyalty_points_adjusted",
        ).first()
        assert audit is not None
        assert "goodwill" in (audit.after_value or "")
