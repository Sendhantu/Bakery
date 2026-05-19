from domains.orders import OrderStatusUpdated
from models import Order
from realtime.events import emit_kds_refresh, emit_order_updated
from utils.notifications import notify_order_status_change


def handle_order_status_updated(event: OrderStatusUpdated):
    order = Order.query.get(event.order_id)
    if order is None:
        return
    notify_order_status_change(
        order,
        event.new_status,
        old_status=event.old_status,
    )
    emit_order_updated(order.id, event.new_status, branch_id=order.branch_id)
    emit_kds_refresh(branch_id=order.branch_id)
