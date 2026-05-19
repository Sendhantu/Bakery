import json

from models import Payment, User, db


def test_healthz_returns_json(client):
    response = client.get("/healthz")
    payload = response.get_json()
    assert response.status_code in {200, 503}
    assert "database" in payload
    assert "redis" in payload


def test_payment_transition_invalid(app):
    with app.app_context():
        from models import Order, User

        user = User.query.filter_by(email="customer@test.com").first()
        order = Order(user_id=user.id, order_number="TEST-INV-1", total=10, subtotal=10)
        db.session.add(order)
        db.session.flush()
        payment = Payment(order_id=order.id, amount=10, method="COD", status="PAID")
        db.session.add(payment)
        db.session.commit()
        try:
            payment.transition_to("PENDING")
            raised = False
        except ValueError:
            raised = True
        assert raised is True


def test_qr_verify_requires_token(client):
    response = client.get("/api/v2/qr/verify")
    assert response.status_code == 400


def test_offline_sync_status_requires_auth(client):
    response = client.get("/api/v2/sync/status")
    assert response.status_code == 403


def test_offline_sync_status_admin(admin_client):
    admin_client.post(
        "/auth/login",
        data={"email": "admin@bakery.com", "password": "Admin@bakery"},
        follow_redirects=True,
    )
    response = admin_client.get("/api/v2/sync/status")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is True
    assert "online" in payload


def test_api_v1_deprecation_headers(client):
    response = client.get("/api/v1/meta")
    assert response.headers.get("X-API-Deprecated") == "true"
    assert "successor-version" in (response.headers.get("Link") or "")
