from datetime import datetime

from domains.orders import OrderStatusUpdated
from exceptions import ValidationError
from models import db
from repositories import OrderRepository
from validators import ensure_order_status_transition


class OrderService:
    def __init__(self, order_repository=None, event_bus=None, audit_service=None):
        self.order_repository = order_repository or OrderRepository()
        self.event_bus = event_bus
        self.audit_service = audit_service

    def update_order_status(self, order_id, new_status, actor="admin", actor_id=None):
        order = self.order_repository.get_or_404(order_id)
        status = ensure_order_status_transition(order.status, new_status, actor=actor)
        old_status = order.status

        with db.session.begin_nested():
            order.status = status
            order.mark_status_change()
            self._sync_delivery_status(order, status)
            if self.audit_service is not None:
                self.audit_service.record(
                    "order_status_changed",
                    "Order",
                    order.id,
                    actor_id=actor_id,
                    branch_id=order.branch_id,
                    metadata={"old_status": old_status, "new_status": status, "actor": actor},
                    change_summary=f"Order status changed from {old_status} to {status}",
                )
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
            delivery.last_status_at = datetime.utcnow()
            delivery.version = int(delivery.version or 0) + 1
            if agent:
                agent.availability = True
            return

        delivery.delivered_time = None
        if new_status == "OUT_FOR_DELIVERY":
            delivery.status = "OUT_FOR_DELIVERY"
            delivery.last_status_at = datetime.utcnow()
            delivery.version = int(delivery.version or 0) + 1
            if agent:
                agent.availability = False
        elif new_status == "PACKED":
            delivery.status = "PACKED"
            delivery.last_status_at = datetime.utcnow()
            delivery.version = int(delivery.version or 0) + 1
            if agent:
                agent.availability = False
        elif new_status == "CANCELLED":
            delivery.status = "CANCELLED"
            delivery.last_status_at = datetime.utcnow()
            delivery.version = int(delivery.version or 0) + 1
            if agent:
                agent.availability = True
        else:
            delivery.status = "ASSIGNED"
            delivery.last_status_at = datetime.utcnow()
            delivery.version = int(delivery.version or 0) + 1
            if agent:
                agent.availability = False
