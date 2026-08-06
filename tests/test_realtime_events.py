from datetime import timedelta

from clock import utcnow
from models import Delivery, DeliveryAgent, User, db
from realtime.events import (
    emit_delivery_assignment,
    emit_new_order,
    emit_order_cancelled,
    emit_order_status_updated,
    emit_order_updated,
    customer_room,
    delivery_agent_room,
)


def _rooms(emitted):
    return [kwargs["room"] for _event, _payload, kwargs in emitted]


def test_new_order_emit_targets_admin_and_kds_rooms_only(
    db_session,
    order_factory,
    socket_emit_spy,
):
    order = order_factory(quantity=2, total=250)
    db_session.commit()

    emit_new_order(order)

    assert [event for event, _payload, _kwargs in socket_emit_spy] == [
        "new_order",
        "new_order",
    ]
    assert _rooms(socket_emit_spy) == ["admin", "kds"]
    assert all(
        kwargs.get("broadcast") is None for _event, _payload, kwargs in socket_emit_spy
    )
    payload = socket_emit_spy[0][1]
    assert payload["order_id"] == order.id
    assert payload["customer_name"]
    assert payload["items_summary"]
    assert payload["total"] == 250.0
    assert payload["created_at"] is not None


def test_delivery_assignment_emit_targets_only_specific_agent_room(
    db_session,
    user_factory,
    order_factory,
    socket_emit_spy,
):
    delivery_user = user_factory(
        email="assignment-agent@test.com",
        role="delivery",
        name="Assignment Agent",
    )
    agent = DeliveryAgent(
        user_id=delivery_user.id,
        name="Assignment Agent",
        phone="8888888888",
    )
    db_session.add(agent)
    db_session.flush()
    order = order_factory(total=310)
    order.special_note = "Leave at counter"
    db_session.add(
        Delivery(
            order_id=order.id,
            agent_id=agent.id,
            assigned_time=utcnow(),
            status="ASSIGNED",
        )
    )
    db_session.commit()

    emit_delivery_assignment(agent.id, order_id=order.id)

    assert len(socket_emit_spy) == 1
    event, payload, kwargs = socket_emit_spy[0]
    assert event == "delivery_assignment"
    assert kwargs["room"] == f"delivery_{agent.id}"
    assert kwargs.get("broadcast") is None
    assert "delivery" not in _rooms(socket_emit_spy)
    assert payload["order_id"] == order.id
    assert payload["delivery_address"]
    assert payload["phone"] == "9999999999"
    assert payload["special_instructions"] == "Leave at counter"


def test_delivery_status_emit_targets_agent_room_not_general_delivery_room(
    db_session,
    user_factory,
    order_factory,
    socket_emit_spy,
):
    delivery_user = user_factory(
        email="status-agent@test.com",
        role="delivery",
        name="Status Agent",
    )
    agent = DeliveryAgent(user_id=delivery_user.id, name="Status Agent")
    db_session.add(agent)
    db_session.flush()
    order = order_factory(status="PACKED", total=215)
    order.delivery_date = utcnow().date() + timedelta(days=1)
    db_session.add(Delivery(order_id=order.id, agent_id=agent.id, status="ASSIGNED"))
    db_session.commit()

    emit_order_updated(order.id, "READY_FOR_PICKUP")

    rooms = _rooms(socket_emit_spy)
    assert "admin" in rooms
    assert "customer" in rooms
    assert "kds" in rooms
    assert f"delivery_{agent.id}" in rooms
    assert "delivery" not in rooms
    assert all(
        kwargs.get("broadcast") is None for _event, _payload, kwargs in socket_emit_spy
    )


def test_admin_status_emit_reaches_admin_kds_customer_and_assigned_agent(
    db_session,
    user_factory,
    order_factory,
    socket_emit_spy,
):
    delivery_user = user_factory(
        email="admin-status-agent@test.com",
        role="delivery",
        name="Admin Status Agent",
    )
    agent = DeliveryAgent(user_id=delivery_user.id, name="Admin Status Agent")
    db_session.add(agent)
    db_session.flush()
    order = order_factory(status="PACKED", total=215)
    db_session.add(Delivery(order_id=order.id, agent_id=agent.id, status="ASSIGNED"))
    db_session.commit()

    emit_order_status_updated(
        order,
        ["admin", "kds", customer_room(order.user_id), delivery_agent_room(agent.id)],
    )

    rooms = _rooms(socket_emit_spy)
    assert rooms == ["admin", "kds", f"customer_{order.user_id}", f"delivery_{agent.id}"]
    assert all(event == "order_status_updated" for event, _payload, _kwargs in socket_emit_spy)
    assert all(
        kwargs.get("broadcast") is None for _event, _payload, kwargs in socket_emit_spy
    )
    payload = socket_emit_spy[0][1]
    assert payload["order_id"] == order.id
    assert payload["new_status"] == "PACKED"
    assert payload["status"] == "PACKED"
    assert payload["detail_url"] == f"/admin/orders/{order.id}"


def test_order_cancellation_emit_reaches_admin_kds_customer_and_assigned_agent(
    db_session,
    user_factory,
    order_factory,
    socket_emit_spy,
):
    delivery_user = user_factory(
        email="cancel-agent@test.com",
        role="delivery",
        name="Cancel Agent",
    )
    agent = DeliveryAgent(user_id=delivery_user.id, name="Cancel Agent")
    db_session.add(agent)
    db_session.flush()
    order = order_factory(status="CANCELLED", total=120)
    db_session.add(Delivery(order_id=order.id, agent_id=agent.id, status="CANCELLED"))
    db_session.commit()

    emit_order_cancelled(order, reason="Customer requested")

    rooms = _rooms(socket_emit_spy)
    assert rooms == [
        "admin",
        "kds",
        f"customer_{order.user_id}",
        f"delivery_{agent.id}",
    ]
    assert "delivery" not in rooms
    assert all(
        kwargs.get("broadcast") is None for _event, _payload, kwargs in socket_emit_spy
    )
    assert all(
        event == "order_cancelled" for event, _payload, _kwargs in socket_emit_spy
    )
