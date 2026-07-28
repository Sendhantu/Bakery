from pathlib import Path

import pytest
import yaml
from flask import Flask

from config.utils import build_engine_options
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
        "FINANCIAL_DATA_ENCRYPTION_KEY": (
            "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY="
        ),
    }
    for name, value in required_values.items():
        monkeypatch.setenv(name, value)


def _set_minimal_render_production_env(monkeypatch):
    required_values = {
        "DATABASE_URL": "mysql+pymysql://user:pass@example.com:4000/bakerydb",
        "REDIS_URL": "redis://localhost:6379/0",
        "SECRET_KEY": "abcdefghijklmnopqrstuvwxyz123456",
        "JWT_SECRET_KEY": "abcdefghijklmnopqrstuvwxyz123456",
        "FINANCIAL_DATA_ENCRYPTION_KEY": (
            "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY="
        ),
    }
    for name, value in required_values.items():
        monkeypatch.setenv(name, value)
    for name in (
        "SOCKETIO_MESSAGE_QUEUE",
        "CELERY_BROKER_URL",
        "CELERY_RESULT_BACKEND",
        "RATELIMIT_STORAGE_URI",
    ):
        monkeypatch.delenv(name, raising=False)


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


def test_production_redis_url_populates_render_backed_settings(monkeypatch):
    _set_minimal_render_production_env(monkeypatch)

    app = _production_config_app()
    app.config["REDIS_URL"] = "redis://localhost:6379/0"
    app.config.pop("SOCKETIO_MESSAGE_QUEUE", None)
    app.config.pop("CELERY_BROKER_URL", None)
    app.config.pop("CELERY_RESULT_BACKEND", None)
    app.config.pop("RATELIMIT_STORAGE_URI", None)

    ProductionConfig.init_app(app)

    assert app.config["SOCKETIO_MESSAGE_QUEUE"] == "redis://localhost:6379/0"
    assert app.config["CELERY_BROKER_URL"] == "redis://localhost:6379/0"
    assert app.config["CELERY_RESULT_BACKEND"] == "redis://localhost:6379/0"
    assert app.config["RATELIMIT_STORAGE_URI"] == "redis://localhost:6379/0"


def test_render_database_pool_defaults_are_conservative(monkeypatch):
    monkeypatch.setenv("RENDER_SERVICE_ID", "srv-test")
    monkeypatch.delenv("DB_POOL_SIZE", raising=False)
    monkeypatch.delenv("DB_MAX_OVERFLOW", raising=False)
    monkeypatch.delenv("DB_POOL_TIMEOUT", raising=False)

    options = build_engine_options(
        "mysql+pymysql://user:pass@example.com:4000/bakerydb"
    )

    assert options["pool_size"] == 5
    assert options["max_overflow"] == 5
    assert options["pool_timeout"] == 10


def test_postgres_engine_options_ignore_mysql_ssl_env(monkeypatch):
    monkeypatch.setenv("DB_SSL_CA", "/etc/ssl/certs/ca-certificates.crt")
    monkeypatch.setenv("DB_SSL_VERIFY_CERT", "true")
    monkeypatch.setenv("DB_SSL_VERIFY_IDENTITY", "true")
    monkeypatch.delenv("DB_SSLMODE", raising=False)
    monkeypatch.delenv("DATABASE_SSLMODE", raising=False)

    options = build_engine_options(
        "postgresql+psycopg://user:pass@example.com:5432/bakerydb"
    )

    assert options.get("connect_args", {}) == {}


def test_postgres_engine_options_allow_sslmode(monkeypatch):
    monkeypatch.setenv("DB_SSLMODE", "require")

    options = build_engine_options(
        "postgresql+psycopg://user:pass@example.com:5432/bakerydb"
    )

    assert options["connect_args"] == {"sslmode": "require"}


def test_mysql_engine_options_include_mysql_ssl_env(monkeypatch):
    monkeypatch.setenv("DB_SSL_CA", "/etc/ssl/certs/ca-certificates.crt")
    monkeypatch.setenv("DB_SSL_VERIFY_CERT", "true")
    monkeypatch.setenv("DB_SSL_VERIFY_IDENTITY", "true")

    options = build_engine_options(
        "mysql+pymysql://user:pass@example.com:4000/bakerydb"
    )

    assert options["connect_args"]["ssl_ca"] == "/etc/ssl/certs/ca-certificates.crt"
    assert options["connect_args"]["ssl_verify_cert"] is True
    assert options["connect_args"]["ssl_verify_identity"] is True


def test_render_blueprint_uses_tidb_and_keyvalue():
    blueprint_path = Path(__file__).resolve().parents[1] / "render.yaml"
    blueprint = yaml.safe_load(blueprint_path.read_text())

    services = {service["name"]: service for service in blueprint["services"]}
    web_env = {
        env_var["key"]: env_var
        for env_var in services["bakery-customer-portal"]["envVars"]
    }
    worker_env = {
        env_var["key"]: env_var
        for env_var in services["bakery-celery-worker"]["envVars"]
    }

    assert "databases" not in blueprint
    assert web_env["PORTAL_ROLE"]["value"] == "customer"
    assert web_env["DATABASE_URL"]["sync"] is False
    assert worker_env["DATABASE_URL"]["fromService"]["name"] == "bakery-customer-portal"
    assert web_env["FINANCIAL_DATA_ENCRYPTION_KEY"]["sync"] is False
    assert (
        worker_env["FINANCIAL_DATA_ENCRYPTION_KEY"]["fromService"]["envVarKey"]
        == "FINANCIAL_DATA_ENCRYPTION_KEY"
    )
    assert services["bakery-redis"]["type"] == "keyvalue"
    assert services["bakery-celery-worker"]["plan"] != "free"

    render_backed_env = (
        services["bakery-customer-portal"]["envVars"]
        + services["bakery-celery-worker"]["envVars"]
    )
    assert web_env["DB_SSL_VERIFY_IDENTITY"]["value"] == "true"
    assert worker_env["DB_SSL_VERIFY_IDENTITY"]["value"] == "true"
    for env_var in render_backed_env:
        source = env_var.get("fromService", {})
        if source.get("name") == "bakery-redis":
            assert source["type"] == "keyvalue"


def test_production_financial_encryption_key_is_required(monkeypatch):
    _set_required_production_env(monkeypatch)
    monkeypatch.delenv("FINANCIAL_DATA_ENCRYPTION_KEY", raising=False)

    with pytest.raises(RuntimeError, match="FINANCIAL_DATA_ENCRYPTION_KEY"):
        ProductionConfig.init_app(_production_config_app())


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
