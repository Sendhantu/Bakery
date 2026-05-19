"""Socket.IO broadcast helpers for cross-portal realtime updates."""

from flask import current_app


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
