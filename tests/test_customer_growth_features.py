from datetime import date, timedelta
from decimal import Decimal

from bootstrap import get_container
from clock import utcnow
from models import (
    Cart,
    CorporateInquiry,
    DeliveryPincodeRule,
    Notification,
    OccasionReminder,
    OccasionReminderLog,
    Order,
    OrderStatusHistory,
    Product,
    ProductVariant,
    User,
    db,
)


def sign_in(test_client, email="customer@test.com", password="customer123"):
    return test_client.post(
        "/auth/login",
        data={"email": email, "password": password},
        follow_redirects=False,
    )


def add_cart_item(app, *, price="100"):
    with app.app_context():
        customer = User.query.filter_by(email="customer@test.com").first()
        product = Product(
            name=f"Growth Feature Cake {price}",
            base_price=Decimal(price),
            is_active=True,
        )
        db.session.add(product)
        db.session.flush()
        variant = ProductVariant(
            product_id=product.id,
            name="Default",
            price=Decimal(price),
            stock=10,
        )
        db.session.add(variant)
        db.session.flush()
        db.session.add(
            Cart(
                user_id=customer.id,
                product_id=product.id,
                variant_id=variant.id,
                quantity=1,
            )
        )
        db.session.commit()
        return product.id, variant.id


def test_delivery_serviceability_blocks_far_location_and_pickup_still_available(client):
    sign_in(client)
    client.application.config["STORE_LATITUDE"] = "11.0168"
    client.application.config["STORE_LONGITUDE"] = "76.9558"
    add_cart_item(client.application, price="200")

    tomorrow = (utcnow().date() + timedelta(days=1)).isoformat()
    response = client.post(
        "/checkout",
        data={
            "fulfillment_type": "DELIVERY",
            "delivery_date": tomorrow,
            "time_slot": "09:00 - 11:00",
            "address_line1": "Far office",
            "city": "Chennai",
            "pincode": "600001",
            "phone": "9999999999",
            "latitude": "13.0827",
            "longitude": "80.2707",
            "payment_method": "COD",
        },
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert b"store-pickup order" in response.data
    with client.application.app_context():
        assert Order.query.filter_by(fulfillment_type="DELIVERY").count() == 0

    pickup_response = client.post(
        "/checkout",
        data={
            "fulfillment_type": "PICKUP",
            "pickup_date": tomorrow,
            "pickup_slot": "09:00 - 11:00",
            "pickup_phone": "9999999999",
            "payment_method": "COD",
        },
        follow_redirects=True,
    )
    assert b"placed successfully" in pickup_response.data


def test_pincode_serviceability_api_returns_configured_fee(client):
    sign_in(client)
    with client.application.app_context():
        db.session.add(
            DeliveryPincodeRule(
                pincode="641010",
                status="supported",
                delivery_fee_override=Decimal("75.00"),
                estimated_delivery_minutes=45,
            )
        )
        db.session.commit()

    response = client.post(
        "/api/delivery/serviceability",
        json={"pincode": "641010", "subtotal": 300},
    )

    assert response.status_code == 200
    assert response.json["serviceable"] is True
    assert response.json["delivery_fee"] == 75.0
    assert response.json["eta_minutes"] == 45


def test_order_status_history_and_tracking_token_page(client):
    sign_in(client)
    add_cart_item(client.application, price="150")
    tomorrow = (utcnow().date() + timedelta(days=1)).isoformat()
    response = client.post(
        "/checkout",
        data={
            "fulfillment_type": "PICKUP",
            "pickup_date": tomorrow,
            "pickup_slot": "09:00 - 11:00",
            "pickup_phone": "9999999999",
            "payment_method": "COD",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    with client.application.app_context():
        order = Order.query.order_by(Order.id.desc()).first()
        token = order.tracking_token
        get_container().order_service.update_order_status(
            order.id,
            "CONFIRMED",
            actor="admin",
            actor_id=None,
            customer_note="Accepted by bakery.",
        )
        assert OrderStatusHistory.query.filter_by(order_id=order.id).count() == 2
        assert Notification.query.filter_by(user_id=order.user_id, type="order").count() >= 1

    track_response = client.get(f"/track/{token}")
    assert track_response.status_code == 200
    assert b"Track Order" in track_response.data
    assert b"Accepted by bakery" in track_response.data


def test_occasion_reminder_task_sends_once(client):
    with client.application.app_context():
        user = User.query.filter_by(email="customer@test.com").first()
        reminder = OccasionReminder(
            user_id=user.id,
            occasion_type="Birthday",
            occasion_date=date(2026, 8, 19),
            preferred_channel="email",
            marketing_consent=True,
            recommendations_enabled=True,
        )
        db.session.add(reminder)
        db.session.commit()

        service = get_container().occasion_reminder_service
        first = service.send_due_reminders(today=date(2026, 8, 9))
        second = service.send_due_reminders(today=date(2026, 8, 9))

        assert first["sent"] == 1
        assert second["sent"] == 0
        assert OccasionReminderLog.query.filter_by(reminder_id=reminder.id).count() == 1


def test_corporate_inquiry_form_persists_and_rejects_bad_gstin(client):
    bad = client.post(
        "/corporate-orders",
        data={
            "contact_name": "Anita",
            "company_name": "Acme",
            "work_email": "anita@example.com",
            "mobile": "9999999999",
            "gstin": "BADGST",
            "delivery_location": "Office",
            "required_date": (utcnow().date() + timedelta(days=3)).isoformat(),
            "products_required": "Brownie boxes",
        },
        follow_redirects=True,
    )
    assert b"valid GSTIN" in bad.data

    good = client.post(
        "/corporate-orders",
        data={
            "contact_name": "Anita",
            "company_name": "Acme Foods",
            "work_email": "anita@example.com",
            "mobile": "9999999999",
            "gstin": "",
            "delivery_location": "Office",
            "required_date": (utcnow().date() + timedelta(days=3)).isoformat(),
            "products_required": "Brownie boxes",
            "people_count": "40",
        },
        follow_redirects=True,
    )

    assert b"Corporate inquiry received" in good.data
    with client.application.app_context():
        inquiry = CorporateInquiry.query.filter_by(company_name="Acme Foods").one()
        assert inquiry.status == "new"
        assert inquiry.people_count == 40
