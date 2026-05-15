from domains.orders import OrderStatusUpdated
from models import Order
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
