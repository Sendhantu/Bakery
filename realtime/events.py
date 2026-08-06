"""Socket.IO broadcast helpers for cross-portal realtime updates."""

from flask import current_app


DELIVERY_RELEVANT_STATUSES = {
    "PACKED",
    "OUT_FOR_DELIVERY",
    "READY_FOR_PICKUP",
    "DELIVERED",
    "CANCELLED",
}


def _emit(event_name, payload, rooms):
    try:
        from models import socketio

        target_rooms = [room for room in rooms if room]
        if not target_rooms:
            target_rooms = ["global"]
        for room in target_rooms:
            socketio.emit(event_name, payload, room=room)
    except Exception:
        current_app.logger.exception("realtime_emit_failed event=%s", event_name)


def emit_order_updated(order_id, status, branch_id=None):
    payload = {"order_id": order_id, "status": status, "branch_id": branch_id}
    rooms = ["admin", "customer", "kds"]
    if status in DELIVERY_RELEVANT_STATUSES:
        try:
            from models import Order, db

            order = db.session.get(Order, order_id)
            room = delivery_agent_room(order.delivery.agent_id if order and order.delivery else None)
            if room:
                rooms.append(room)
        except Exception:
            current_app.logger.exception("delivery_status_room_lookup_failed order_id=%s", order_id)
    _emit("order_updated", payload, rooms)


def customer_room(user_id):
    return f"customer_{user_id}" if user_id else None


def delivery_agent_room(agent_id):
    return f"delivery_{agent_id}" if agent_id else None


def _isoformat(value):
    return value.isoformat() if value else None


def _order_item_summary(order):
    items = order.items.all()
    parts = [
        f"{item.product_name} x{item.quantity}"
        for item in items[:3]
    ]
    if len(items) > 3:
        parts.append(f"+{len(items) - 3} more")
    return ", ".join(parts)


def _delivery_address(order):
    parts = [
        order.address_line1,
        order.address_line2,
        order.city,
        order.pincode,
    ]
    return ", ".join(str(part) for part in parts if part)


def emit_new_order(order):
    created_at = _isoformat(order.placed_at)
    payload = {
        "order_id": order.id,
        "order_number": order.order_number,
        "customer_name": order.customer.name if order.customer else "Customer",
        "item_summary": _order_item_summary(order),
        "items_summary": _order_item_summary(order),
        "total": float(order.total or 0),
        "created_at": created_at,
        "timestamp": created_at,
        "status": order.status,
        "detail_url": f"/admin/orders/{order.id}",
    }
    _emit("new_order", payload, ["admin", "kds"])


def emit_order_status_updated(order, rooms):
    payload = {
        "order_id": order.id,
        "order_number": order.order_number,
        "status": order.status,
        "new_status": order.status,
        "updated_at": _isoformat(order.updated_at),
        "detail_url": f"/admin/orders/{order.id}",
    }
    _emit("order_status_updated", payload, rooms)


def emit_order_reversal(order, event_name, reason=""):
    payload = {
        "order_id": order.id,
        "order_number": order.order_number,
        "status": order.status,
        "payment_status": order.payment_status,
        "reason": reason,
        "updated_at": _isoformat(order.updated_at),
        "detail_url": f"/admin/orders/{order.id}",
    }
    rooms = ["admin", "kds", customer_room(order.user_id)]
    if order.delivery:
        rooms.append(delivery_agent_room(order.delivery.agent_id))
    _emit(event_name, payload, rooms)


def emit_order_cancelled(order, reason=""):
    emit_order_reversal(order, "order_cancelled", reason=reason)


def emit_order_refunded(order, reason=""):
    emit_order_reversal(order, "order_refunded", reason=reason)


def emit_stock_updated(item, include_customer=False):
    rooms = ["admin"]
    if include_customer:
        rooms.append("customer")
    if hasattr(item, "product_id"):
        payload = {
            "item_type": "product_variant",
            "product_id": item.product_id,
            "variant_id": item.id,
            "new_stock": int(item.stock or 0),
        }
    else:
        payload = {
            "item_type": "raw_material",
            "raw_material_id": item.id,
            "material_id": item.id,
            "name": item.name,
            "unit": item.unit,
            "new_stock": float(item.stock or 0),
            "reorder_level": float(item.reorder_level or 0),
            "stock_status": item.stock_status,
        }
    _emit("stock_updated", payload, rooms)


def emit_support_message(message, customer_id):
    payload = {
        "message_id": message.id,
        "customer_id": customer_id,
        "sender_id": message.sender_id,
        "receiver_id": message.receiver_id,
        "sender_name": message.sender.name if message.sender else "Support",
        "sender_role": message.sender.role if message.sender else "",
        "content": message.content,
        "sent_at": _isoformat(message.sent_at),
        "thread_url": f"/admin/chat/{customer_id}",
    }
    _emit("support_message", payload, ["admin", customer_room(customer_id)])


def emit_kds_refresh(branch_id=None):
    _emit("kds_refresh", {"branch_id": branch_id}, ["admin", "kds"])


def emit_delivery_assignment(agent_id, order_id=None):
    payload = {"agent_id": agent_id, "order_id": order_id}
    if order_id:
        try:
            from models import Order, db

            order = db.session.get(Order, order_id)
            if order:
                payload.update(
                    {
                        "order_number": order.order_number,
                        "customer_name": order.customer.name if order.customer else "Customer",
                        "delivery_address": _delivery_address(order),
                        "phone": order.phone,
                        "item_summary": _order_item_summary(order),
                        "items_summary": _order_item_summary(order),
                        "special_instructions": order.special_note or "",
                        "total": float(order.total or 0),
                        "status": order.status,
                        "assigned_at": _isoformat(
                            order.delivery.assigned_time if order.delivery else None
                        ),
                        "detail_url": f"/delivery/order/{order.id}",
                    }
                )
        except Exception:
            current_app.logger.exception("delivery_assignment_payload_failed order_id=%s", order_id)

    _emit("delivery_assignment", payload, [delivery_agent_room(agent_id)])


def emit_analytics_updated(summary=None):
    _emit("analytics_updated", {"summary": summary or {}}, ["admin"])
