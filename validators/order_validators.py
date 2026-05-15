from exceptions import ValidationError
from models import can_transition_order_status


def ensure_order_status_transition(current_status, new_status, actor="admin"):
    status = (new_status or "").strip().upper()
    if not status:
        raise ValidationError("Please choose a valid status.")
    if not can_transition_order_status(current_status, status, actor=actor):
        raise ValidationError("That status change is not allowed right now.")
    return status
