import hmac
import hashlib
from datetime import timedelta

import pytest

from clock import utcnow
from exceptions import ValidationError
from models import (
    Branch,
    ConversionEvent,
    DiningTable,
    KitchenAlert,
    NotificationDeliveryLog,
    SecurityEvent,
    TableMenuScan,
    WebhookEventLog,
    db,
)


def create_branch(name):
    branch = Branch(name=name, phone="9999999999", address="Test Street", is_active=True)
    db.session.add(branch)
    db.session.flush()
    return branch


def sign_in(test_client, email="admin@bakery.com", password="Admin@bakery"):
    return test_client.post(
        "/auth/login",
        data={"email": email, "password": password},
        follow_redirects=False,
    )


def test_new_admin_sections_render_for_owner(admin_client, admin_app):
    assert sign_in(admin_client).status_code == 302
    for path in ("/admin/security", "/admin/notifications", "/admin/table-qr"):
        response = admin_client.get(path)
        assert response.status_code == 200


def test_signed_webhook_rejects_invalid_signature_and_logs(client, app):
    app.config["PAYMENT_WEBHOOK_SECRET"] = "test-secret"
    response = client.post(
        "/api/webhooks/payment",
        data=b'{"id":"evt_1"}',
        headers={
            "X-Webhook-Event-Id": "evt_1",
            "X-Webhook-Signature": "bad",
        },
        content_type="application/json",
    )

    assert response.status_code == 401
    with app.app_context():
        log = WebhookEventLog.query.filter_by(provider="payment", event_id="evt_1").one()
        assert log.signature_status == "invalid"
        assert SecurityEvent.query.filter_by(event_type="webhook_signature_failed").count() == 1


def test_signed_webhook_accepts_signature_once_and_marks_replay(client, app):
    app.config["PAYMENT_WEBHOOK_SECRET"] = "test-secret"
    payload = b'{"id":"evt_2"}'
    signature = hmac.new(b"test-secret", payload, hashlib.sha256).hexdigest()

    first = client.post(
        "/api/webhooks/payment",
        data=payload,
        headers={
            "X-Webhook-Event-Id": "evt_2",
            "X-Webhook-Signature": signature,
        },
        content_type="application/json",
    )
    second = client.post(
        "/api/webhooks/payment",
        data=payload,
        headers={
            "X-Webhook-Event-Id": "evt_2",
            "X-Webhook-Signature": signature,
        },
        content_type="application/json",
    )

    assert first.status_code == 200
    assert second.status_code == 401
    with app.app_context():
        log = WebhookEventLog.query.filter_by(provider="payment", event_id="evt_2").one()
        assert log.signature_status == "valid"
        assert log.processing_status == "duplicate"
        assert log.replayed is True


def test_conversion_events_require_consent(client, app):
    response = client.post(
        "/api/analytics/conversion",
        json={"event_name": "add_to_cart", "event_id": "cart-denied"},
    )
    assert response.status_code == 200
    assert response.get_json()["recorded"] is False

    client.post("/api/consent", json={"category": "analytics", "status": "granted"})
    response = client.post(
        "/api/analytics/conversion",
        json={
            "event_name": "add_to_cart",
            "event_id": "cart-allowed",
            "metadata": {"quantity": 1, "email": "blocked@example.com"},
        },
    )

    assert response.status_code == 200
    assert response.get_json()["recorded"] is True
    with app.app_context():
        event = ConversionEvent.query.filter_by(event_id="cart-allowed").one()
        assert '"quantity": 1' in event.metadata_json
        assert "blocked@example.com" not in event.metadata_json


def test_notification_engine_validates_variables_and_dedupes(order_factory, app):
    with app.app_context():
        order = order_factory()
        engine = app.extensions["service_container"].notification_engine

        with pytest.raises(ValidationError):
            engine.upsert_template(
                event_type="order_placed",
                channel="sms",
                name="Bad",
                body="Hi {{password}}",
            )

        engine.notify_order_event(order, "order_placed", channels=("in_app",))
        engine.notify_order_event(order, "order_placed", channels=("in_app",))
        engine.create_kitchen_alert(order)
        engine.create_kitchen_alert(order)
        db.session.commit()

        assert NotificationDeliveryLog.query.filter_by(order_id=order.id).count() == 1
        assert KitchenAlert.query.filter_by(order_id=order.id).count() == 1


def test_table_qr_menu_validates_token_records_scan_and_expires_session(client, app):
    with app.app_context():
        branch = create_branch("QR Branch 12")
        table = app.extensions["service_container"].table_qr_service.create_table(
            branch_id=branch.id,
            table_number="T12",
            display_name="Table 12",
            seating_capacity=4,
        )
        db.session.commit()
        token = table.qr_token

    response = client.get(f"/menu/{token}")
    assert response.status_code == 200
    assert b"Ordering for Table 12" in response.data

    with app.app_context():
        table = DiningTable.query.filter_by(table_number="T12").one()
        assert TableMenuScan.query.filter_by(table_id=table.id).count() == 1
        session_row = table.menu_sessions.first()
        session_row.expires_at = utcnow() - timedelta(minutes=1)
        db.session.commit()

    with client.session_transaction() as sess:
        assert "table_menu" in sess

    assert client.get("/checkout").status_code in {302, 308}


def test_regenerating_table_qr_invalidates_old_token(client, app):
    with app.app_context():
        branch = create_branch("QR Branch 13")
        service = app.extensions["service_container"].table_qr_service
        table = service.create_table(
            branch_id=branch.id,
            table_number="T13",
            display_name="Table 13",
        )
        db.session.commit()
        old_token = table.qr_token
        service.regenerate_token(table)
        db.session.commit()
        new_token = table.qr_token

    assert client.get(f"/menu/{old_token}").status_code == 404
    assert client.get(f"/menu/{new_token}").status_code == 200
