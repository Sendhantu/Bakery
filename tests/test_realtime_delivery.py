from datetime import timedelta

from flask_login import login_user

import app as app_module
from clock import utcnow
from models import (
    Delivery,
    DeliveryAgent,
    Order,
    OrderItem,
    Product,
    User,
    db,
    socketio,
)
from realtime.events import emit_delivery_assignment, emit_order_updated


def _create_assigned_order(app):
    with app.app_context():
        customer = User.query.filter_by(email="customer@test.com").first()
        agent = DeliveryAgent.query.first()
        product = Product.query.first()
        assert customer is not None
        assert agent is not None
        assert product is not None

        order = Order(
            order_number=Order.generate_order_number(),
            user_id=customer.id,
            status="PLACED",
            subtotal=250,
            total=250,
            address_line1="12 Test Street",
            address_line2="Near Market",
            city="Coimbatore",
            pincode="641002",
            phone="9999999999",
            delivery_slot="09:00 - 11:00",
            delivery_date=utcnow().date() + timedelta(days=1),
            special_note="Ring the bell",
        )
        db.session.add(order)
        db.session.flush()
        db.session.add(
            OrderItem(
                order_id=order.id,
                product_id=product.id,
                product_name=product.name,
                quantity=2,
                unit_price=125,
                subtotal=250,
            )
        )
        db.session.add(
            Delivery(
                order_id=order.id,
                agent_id=agent.id,
                assigned_time=utcnow(),
                status="ASSIGNED",
            )
        )
        db.session.commit()
        return order.id, agent.id


def test_delivery_socket_connect_joins_authenticated_agent_room(app, monkeypatch):
    with app.app_context():
        user = User.query.filter_by(email="delivery@bakery.com").first()
        assert user is not None
        agent = DeliveryAgent.query.filter_by(user_id=user.id).first()
        assert agent is not None

    joined_rooms = []
    monkeypatch.setattr(app_module, "join_room", joined_rooms.append)

    with app.test_request_context("/socket.io/?portal=delivery"):
        login_user(user)
        app_module.handle_socket_connect()

    assert "delivery" in joined_rooms
    assert f"delivery_{agent.id}" in joined_rooms
    assert "global" in joined_rooms


def test_delivery_assignment_targets_only_assigned_agent_room(app, monkeypatch):
    order_id, agent_id = _create_assigned_order(app)
    emitted = []

    def fake_emit(event, payload, **kwargs):
        emitted.append((event, payload, kwargs))

    monkeypatch.setattr(socketio, "emit", fake_emit)

    with app.app_context():
        emit_delivery_assignment(agent_id, order_id=order_id)

    assert len(emitted) == 1
    event, payload, kwargs = emitted[0]
    assert event == "delivery_assignment"
    assert kwargs["room"] == f"delivery_{agent_id}"
    assert kwargs.get("broadcast") is None
    assert payload["order_id"] == order_id
    assert payload["customer_name"]
    assert payload["delivery_address"]
    assert payload["phone"] == "9999999999"
    assert payload["items_summary"]
    assert payload["special_instructions"] == "Ring the bell"


def test_delivery_relevant_status_targets_agent_room_not_delivery_room(
    app, monkeypatch
):
    order_id, agent_id = _create_assigned_order(app)
    emitted = []

    def fake_emit(event, payload, **kwargs):
        emitted.append((event, payload, kwargs))

    monkeypatch.setattr(socketio, "emit", fake_emit)

    with app.app_context():
        emit_order_updated(order_id, "PACKED")

    rooms = [kwargs["room"] for _event, _payload, kwargs in emitted]
    assert f"delivery_{agent_id}" in rooms
    assert "delivery" not in rooms
    assert all(kwargs.get("broadcast") is None for _event, _payload, kwargs in emitted)
