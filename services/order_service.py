from datetime import datetime

from domains.orders import OrderStatusUpdated
from exceptions import ValidationError
from models import db
from repositories import OrderRepository
from validators import ensure_order_status_transition


class OrderService:
    def __init__(self, order_repository=None, event_bus=None):
        self.order_repository = order_repository or OrderRepository()
        self.event_bus = event_bus

    def update_order_status(self, order_id, new_status, actor="admin"):
        order = self.order_repository.get_or_404(order_id)
        status = ensure_order_status_transition(order.status, new_status, actor=actor)
        old_status = order.status

        order.status = status
        order.updated_at = datetime.utcnow()
        self._sync_delivery_status(order, status)
        db.session.commit()

        if self.event_bus is not None:
            self.event_bus.publish(
                OrderStatusUpdated(
                    order_id=order.id,
                    old_status=old_status,
                    new_status=status,
                )
            )
        return order

    def _sync_delivery_status(self, order, new_status):
        delivery = order.delivery
        if delivery is None:
            return

        agent = delivery.agent
        if new_status == "DELIVERED":
            delivery.status = "DELIVERED"
            delivery.delivered_time = datetime.utcnow()
            if agent:
                agent.availability = True
            return

        delivery.delivered_time = None
        if new_status == "OUT_FOR_DELIVERY":
            delivery.status = "OUT_FOR_DELIVERY"
            if agent:
                agent.availability = False
        elif new_status == "PACKED":
            delivery.status = "PACKED"
            if agent:
                agent.availability = False
        elif new_status == "CANCELLED":
            delivery.status = "CANCELLED"
            if agent:
                agent.availability = True
        else:
            delivery.status = "ASSIGNED"
            if agent:
                agent.availability = False
