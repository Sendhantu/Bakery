import pytest
from flask import Flask

from config.production import ProductionConfig
from models import Payment, db


def _set_required_production_env(monkeypatch):
    required_values = {
        "DATABASE_URL": "mysql+pymysql://user:pass@example.com:4000/bakerydb",
        "REDIS_URL": "redis://localhost:6379/0",
        "SOCKETIO_MESSAGE_QUEUE": "redis://localhost:6379/0",
        "CELERY_BROKER_URL": "redis://localhost:6379/0",
        "CELERY_RESULT_BACKEND": "redis://localhost:6379/0",
        "RATELIMIT_STORAGE_URI": "redis://localhost:6379/0",
        "SECRET_KEY": "abcdefghijklmnopqrstuvwxyz123456",
        "JWT_SECRET_KEY": "abcdefghijklmnopqrstuvwxyz123456",
    }
    for name, value in required_values.items():
        monkeypatch.setenv(name, value)


def _production_config_app():
    app = Flask(__name__)
    app.config["SECRET_KEY"] = "abcdefghijklmnopqrstuvwxyz123456"
    app.config["SQLALCHEMY_DATABASE_URI"] = (
        "mysql+pymysql://user:pass@example.com:4000/bakerydb"
    )
    app.config["RATELIMIT_STORAGE_URI"] = "redis://localhost:6379/0"
    return app


def test_production_cloudinary_optional_for_startup(monkeypatch):
    _set_required_production_env(monkeypatch)
    monkeypatch.delenv("CLOUDINARY_CLOUD_NAME", raising=False)
    monkeypatch.delenv("CLOUDINARY_API_KEY", raising=False)
    monkeypatch.delenv("CLOUDINARY_API_SECRET", raising=False)

    app = _production_config_app()
    ProductionConfig.init_app(app)

    assert app.config["STORAGE_REQUIRED"] is False


def test_production_cloudinary_required_when_storage_required(monkeypatch):
    _set_required_production_env(monkeypatch)
    monkeypatch.setenv("STORAGE_REQUIRED", "true")
    monkeypatch.delenv("CLOUDINARY_CLOUD_NAME", raising=False)
    monkeypatch.delenv("CLOUDINARY_API_KEY", raising=False)
    monkeypatch.delenv("CLOUDINARY_API_SECRET", raising=False)

    with pytest.raises(RuntimeError, match="CLOUDINARY_API_KEY"):
        ProductionConfig.init_app(_production_config_app())


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
