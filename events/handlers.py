from domains.orders import OrderStatusUpdated
from flask import current_app
from models import Order, db
from realtime.events import (
    customer_room,
    delivery_agent_room,
    emit_kds_refresh,
    emit_order_status_updated,
)
from utils.notifications import notify_order_status_change


def _order_status_rooms(order):
    rooms = ["admin", "kds", customer_room(order.user_id)]
    if order.delivery:
        rooms.append(delivery_agent_room(order.delivery.agent_id))
    return rooms


def handle_order_status_updated(event: OrderStatusUpdated):
    order = db.session.get(Order, event.order_id)
    if order is None:
        return
    try:
        notify_order_status_change(
            order,
            event.new_status,
            old_status=event.old_status,
        )
    except Exception:
        db.session.rollback()
        current_app.logger.exception(
            "order_status_notification_failed order_id=%s status=%s",
            event.order_id,
            event.new_status,
        )
    emit_order_status_updated(order, _order_status_rooms(order))
    emit_kds_refresh(branch_id=order.branch_id)
