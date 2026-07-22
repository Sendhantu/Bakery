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
    _emit("order_updated", payload, ["admin", "delivery", "customer", "kds"])


def customer_room(user_id):
    return f"customer_{user_id}" if user_id else None


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


def emit_new_order(order):
    payload = {
        "order_id": order.id,
        "order_number": order.order_number,
        "customer_name": order.customer.name if order.customer else "Customer",
        "item_summary": _order_item_summary(order),
        "total": float(order.total or 0),
        "timestamp": _isoformat(order.placed_at),
        "detail_url": f"/admin/orders/{order.id}",
    }
    _emit("new_order", payload, ["admin", "kds"])


def emit_order_status_updated(order, rooms):
    payload = {
        "order_id": order.id,
        "new_status": order.status,
        "updated_at": _isoformat(order.updated_at),
    }
    _emit("order_status_updated", payload, rooms)


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


def emit_kds_refresh(branch_id=None):
    _emit("kds_refresh", {"branch_id": branch_id}, ["admin", "kds"])


def emit_delivery_assignment(agent_id, order_id=None):
    _emit(
        "delivery_updated",
        {"agent_id": agent_id, "order_id": order_id},
        ["delivery", "admin"],
    )


def emit_analytics_updated(summary=None):
    _emit("analytics_updated", {"summary": summary or {}}, ["admin"])
