from dataclasses import dataclass


@dataclass(frozen=True)
class OrderStatusUpdated:
    order_id: int
    old_status: str
    new_status: str
