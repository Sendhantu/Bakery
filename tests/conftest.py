import os
import tempfile
import uuid
from datetime import timedelta
from decimal import Decimal

import pytest

from app import create_app, seed_data
from clock import utcnow
from models import (
    Category,
    Order,
    OrderItem,
    Product,
    ProductMaterial,
    ProductVariant,
    RawMaterial,
    User,
    db,
    socketio,
)


@pytest.fixture()
def app_factory(monkeypatch):
    db_fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(db_fd)
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")

    created_apps = []

    def _make(portal_role="customer"):
        app = create_app("testing", portal_role=portal_role)
        created_apps.append(app)
        with app.app_context():
            from models import safe_create_all

            safe_create_all(app)
            seed_data(app)
        return app

    yield _make

    for app in created_apps:
        with app.app_context():
            db.session.remove()
            db.drop_all()

    if os.path.exists(db_path):
        os.unlink(db_path)


@pytest.fixture(autouse=True)
def external_service_stubs(monkeypatch):
    """Keep tests hermetic: no email/SMS/push/weather/LLM network calls."""

    sent_messages = []

    class _DelayStub:
        def delay(self, *args, **kwargs):
            sent_messages.append((args, kwargs))
            return None

    monkeypatch.setattr("tasks.messaging.send_email", _DelayStub(), raising=False)
    monkeypatch.setattr("tasks.messaging.send_sms", _DelayStub(), raising=False)
    monkeypatch.setattr(
        "tasks.messaging.send_whatsapp_message",
        _DelayStub(),
        raising=False,
    )
    monkeypatch.setattr("utils.notifications.send_email", _DelayStub(), raising=False)
    monkeypatch.setattr("utils.notifications.send_sms", _DelayStub(), raising=False)
    monkeypatch.setattr(
        "utils.notifications.send_whatsapp_message",
        _DelayStub(),
        raising=False,
    )
    monkeypatch.setattr(
        "services.push_service.PushService.send_to_user",
        lambda self, user_id, title, body, data=None: 0,
        raising=False,
    )
    monkeypatch.setattr(
        "services.weather_service.requests.get",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            RuntimeError("Weather API disabled in tests")
        ),
        raising=False,
    )
    monkeypatch.setattr(
        "services.route_planning_service.requests.get",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            RuntimeError("Route planning API disabled in tests")
        ),
        raising=False,
    )
    monkeypatch.setattr(
        "services.demand_service.requests.post",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            RuntimeError("Ollama HTTP calls disabled in tests")
        ),
        raising=False,
    )
    monkeypatch.setattr(
        "utils.maps.urlopen",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            RuntimeError("Reverse geocoding disabled in tests")
        ),
        raising=False,
    )
    monkeypatch.setattr("recommendation_engine.Llama", None, raising=False)
    return sent_messages


@pytest.fixture()
def app(app_factory):
    return app_factory("customer")


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def admin_app(app_factory):
    return app_factory("admin")


@pytest.fixture()
def admin_client(admin_app):
    return admin_app.test_client()


@pytest.fixture()
def delivery_app(app_factory):
    return app_factory("delivery")


@pytest.fixture()
def delivery_client(delivery_app):
    return delivery_app.test_client()


@pytest.fixture()
def db_session(app):
    """Provide a test DB session and rollback any uncommitted work on teardown.

    Each app fixture already points at a disposable SQLite database; this fixture
    gives service-level tests a consistent session object and an extra rollback
    boundary for tests that do not intentionally commit.
    """
    with app.app_context():
        yield db.session
        db.session.rollback()


@pytest.fixture()
def user_factory(db_session):
    def _create(
        *,
        email,
        password="Password1",
        role="customer",
        admin_tier="owner",
        name="Test User",
        is_active=True,
    ):
        user = User(
            name=name,
            email=email,
            role=role,
            admin_tier=admin_tier,
            is_active=is_active,
        )
        user.set_password(password)
        db_session.add(user)
        db_session.flush()
        return user

    return _create


@pytest.fixture()
def admin_user_factory(user_factory):
    def _create(*, email, tier="owner", password="AdminTier1", name=None):
        return user_factory(
            email=email,
            password=password,
            role="admin",
            admin_tier=tier,
            name=name or f"{tier.title()} Admin",
        )

    return _create


@pytest.fixture()
def raw_material_factory(db_session):
    def _create(
        *,
        name=None,
        stock=Decimal("10"),
        reorder_level=Decimal("2"),
        unit="kg",
        cost_per_unit=Decimal("40"),
    ):
        material = RawMaterial(
            name=name or f"Test Flour {uuid.uuid4().hex[:8]}",
            stock=Decimal(str(stock)),
            reorder_level=Decimal(str(reorder_level)),
            unit=unit,
            cost_per_unit=Decimal(str(cost_per_unit)),
            is_active=True,
        )
        db_session.add(material)
        db_session.flush()
        return material

    return _create


@pytest.fixture()
def product_factory(db_session, raw_material_factory):
    def _create(
        *,
        name=None,
        price=Decimal("100"),
        variant_stock=10,
        recipe=None,
    ):
        product_name = name or f"Test Cake {uuid.uuid4().hex[:8]}"
        category = Category.query.filter_by(name="Test Category").first()
        if category is None:
            category = Category(name="Test Category", icon="🎂")
            db_session.add(category)
            db_session.flush()
        product = Product(
            name=product_name,
            base_price=Decimal(str(price)),
            category_id=category.id,
            is_active=True,
        )
        variant = ProductVariant(
            product=product,
            name="Default",
            price=Decimal(str(price)),
            stock=variant_stock,
        )
        db_session.add_all([product, variant])
        db_session.flush()
        recipe_rows = recipe or [
            (raw_material_factory(name=f"{product_name} Flour"), Decimal("1"))
        ]
        for material, quantity in recipe_rows:
            db_session.add(
                ProductMaterial(
                    product_id=product.id,
                    raw_material_id=material.id,
                    quantity_required=Decimal(str(quantity)),
                )
            )
        db_session.flush()
        return product, variant

    return _create


@pytest.fixture()
def order_factory(db_session, product_factory):
    def _create(
        *,
        customer=None,
        status="PLACED",
        payment_status="PENDING",
        quantity=1,
        total=Decimal("100"),
        product=None,
        variant=None,
    ):
        if customer is None:
            customer = User.query.filter_by(email="customer@test.com").first()
        if product is None or variant is None:
            product, variant = product_factory()
        order = Order(
            order_number=Order.generate_order_number(),
            user_id=customer.id,
            status=status,
            subtotal=Decimal(str(total)),
            total=Decimal(str(total)),
            payment_status=payment_status,
            address_line1="1 Test Lane",
            city="Coimbatore",
            pincode="641002",
            phone="9999999999",
            delivery_slot="09:00 - 11:00",
            delivery_date=utcnow().date() + timedelta(days=1),
        )
        db_session.add(order)
        db_session.flush()
        item = OrderItem(
            order_id=order.id,
            product_id=product.id,
            variant_id=variant.id,
            product_name=product.name,
            variant_name=variant.name,
            quantity=quantity,
            unit_price=Decimal(str(total)) / Decimal(str(quantity or 1)),
            subtotal=Decimal(str(total)),
        )
        db_session.add(item)
        db_session.flush()
        return order

    return _create


@pytest.fixture()
def socket_emit_spy(monkeypatch):
    emitted = []

    def fake_emit(event, payload, **kwargs):
        emitted.append((event, payload, kwargs))

    monkeypatch.setattr(socketio, "emit", fake_emit)
    return emitted
